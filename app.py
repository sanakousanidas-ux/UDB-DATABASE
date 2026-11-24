"""
Rate limiter backend - Flask + MongoDB (document data model).

Algorithm: fixed window counter.
  Each (client, time window) pair is stored as one small document:
      { _id: "<client>:<window_start>", client, window_start, count, expireAt }
  An atomic upsert with $inc counts the request, so concurrent requests
  cannot read a stale count. A TTL index on `expireAt` lets MongoDB delete
  old windows automatically.
"""
import math
import os
import time

from flask import Flask, jsonify, request, g
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from datetime import datetime, timedelta, timezone

LIMIT = int(os.getenv("RATE_LIMIT", 5))               # max requests
WINDOW_SECONDS = int(os.getenv("RATE_WINDOW", 60))    # per this many seconds
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

app = Flask(__name__)
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
counters = client["rate_limiter_db"]["request_counters"]

# TTL index: MongoDB removes a document once its expireAt time has passed.
try:
    counters.create_index("expireAt", expireAfterSeconds=0)
except PyMongoError:
    pass  # DB not reachable yet; requests will fail open below


def client_id():
    """Identify the caller: API key if given, otherwise IP address."""
    return request.headers.get("X-API-Key") or request.remote_addr


def register_request(cid):
    """Atomically count this request and return the new count + window end."""
    now = time.time()
    window_start = int(now // WINDOW_SECONDS) * WINDOW_SECONDS
    window_end = window_start + WINDOW_SECONDS
    doc_id = f"{cid}:{window_start}"
    expire_at = datetime.fromtimestamp(window_end, tz=timezone.utc) + timedelta(seconds=WINDOW_SECONDS)

    for _ in range(2):  # retry once if two first-requests race to create the doc
        try:
            doc = counters.find_one_and_update(
                {"_id": doc_id},
                {"$inc": {"count": 1},
                 "$setOnInsert": {"client": cid, "window_start": window_start, "expireAt": expire_at}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            return doc["count"], window_end - now
        except DuplicateKeyError:
            continue
    raise PyMongoError("could not update counter")


@app.before_request
def rate_limit():
    if not request.path.startswith("/api/"):
        return None
    try:
        count, seconds_left = register_request(client_id())
    except PyMongoError:
        # Fail open: if the database is down, do not block genuine users.
        g.remaining = None
        return None
    g.remaining = max(0, LIMIT - count)
    if count > LIMIT:
        retry_after = max(1, math.ceil(seconds_left))
        resp = jsonify(error="Too Many Requests",
                       message=f"Limit of {LIMIT} requests per {WINDOW_SECONDS}s exceeded.",
                       retry_after_seconds=retry_after)
        resp.status_code = 429
        resp.headers["Retry-After"] = str(retry_after)
        resp.headers["X-RateLimit-Limit"] = str(LIMIT)
        resp.headers["X-RateLimit-Remaining"] = "0"
        return resp
    return None


@app.after_request
def add_headers(resp):
    remaining = getattr(g, "remaining", None)
    if remaining is not None and resp.status_code != 429:
        resp.headers["X-RateLimit-Limit"] = str(LIMIT)
        resp.headers["X-RateLimit-Remaining"] = str(remaining)
    return resp


@app.route("/")
def home():
    return jsonify(message="Rate limiter running", limit=LIMIT, window_seconds=WINDOW_SECONDS)


@app.route("/api/data")
def data():
    return jsonify(message="Request successful", client=client_id())


if __name__ == "__main__":
    app.run(debug=True, port=5000)
