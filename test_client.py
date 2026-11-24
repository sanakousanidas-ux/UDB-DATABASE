"""Sends 7 quick requests; with a limit of 5 the last two should return 429."""
import requests

for i in range(1, 8):
    res = requests.get("http://localhost:5000/api/data")
    print(i, res.status_code, res.headers.get("X-RateLimit-Remaining"), res.json())
