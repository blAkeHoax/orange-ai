import urllib.request
import urllib.error
import json
import time

url = "https://orange-api-cuuo.onrender.com/assist"
payload = {
    "message": "Explain in two short sentences what Orange AI does.",
    "history": [],
    "profile": ""
}
body = json.dumps(payload).encode("utf-8")
print(f"Sending POST to {url}...")
print("Payload:", json.dumps(payload))

req = urllib.request.Request(
    url,
    data=body,
    headers={
        "Content-Type": "application/json",
        "User-Agent": "OrangeAIDesktop/1.0"
    },
    method="POST"
)

t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        dur = time.time() - t0
        print(f"HTTP Status: {resp.status} (took {dur:.2f}s)")
        data = resp.read().decode("utf-8")
        print("Raw response body:")
        print(data)
except urllib.error.HTTPError as e:
    dur = time.time() - t0
    print(f"HTTPError {e.code} after {dur:.2f}s: {e.reason}")
    print("Error body:", e.read().decode("utf-8", errors="replace"))
except Exception as e:
    dur = time.time() - t0
    print(f"Exception ({type(e).__name__}) after {dur:.2f}s: {e}")
