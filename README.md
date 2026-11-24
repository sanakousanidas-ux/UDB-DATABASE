# Rate Limiter (Flask + MongoDB)

A rate limiter backend built on MongoDB's document data model.
Default limit: 5 requests per 60 seconds per client. Extra requests get HTTP 429.

## How it works
- Client is identified by the `X-API-Key` header, or by IP address if no key is sent.
- For each client and time window, one document is stored in `rate_limiter_db.request_counters`:
  `{ _id: "<client>:<window_start>", client, window_start, count, expireAt }`
- Every request runs an atomic `find_one_and_update` with `$inc` and `upsert`, so concurrent requests cannot bypass the limit.
- If `count` goes above the limit, the server returns HTTP 429 with a `Retry-After` header.
- A TTL index on `expireAt` makes MongoDB delete old windows automatically.
- If MongoDB is unreachable the limiter fails open (requests are allowed).

## Run
```bash
pip install -r requirements.txt
# start MongoDB locally (mongod) or use a MongoDB Atlas URI
python app.py
python test_client.py     # in another terminal
```

## Configuration (environment variables)
`RATE_LIMIT` (default 5), `RATE_WINDOW` seconds (default 60), `MONGO_URI` (default mongodb://localhost:27017)

## Endpoints
- `GET /` - status (not limited)
- `GET /api/data` - rate-limited endpoint
