import urllib.request
import urllib.error
import json
import time

url = "https://orange-api-cuuo.onrender.com/health"
print("Attempting to connect to:", url)
t0 = time.time()
req = urllib.request.Request(url, headers={"User-Agent": "OrangeAIDesktop/1.0"})
try:
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        print("Status code:", resp.status)
        data = resp.read().decode("utf-8")
        print("Body:", data)
except urllib.error.HTTPError as e:
    print(f"HTTPError: {e.code} - {e.reason}")
    print("Body:", e.read().decode("utf-8", errors="replace"))
except Exception as e:
    print(f"Exception ({type(e).__name__}): {e}")
print(f"Total time: {time.time() - t0:.2f}s")
