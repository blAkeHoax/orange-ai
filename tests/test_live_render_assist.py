import sys
import json
import time

sys.path.insert(0, r"D:\Orange AI\Orange AI Desktop")
from brain.api_client import OrangeAPIClient

client = OrangeAPIClient(api_url="https://orange-api-cuuo.onrender.com")
print(f"Testing client with api_url: {client.api_url}")

print("Checking availability...")
t0 = time.time()
avail = client.is_available(timeout=5.0)
print(f"is_available: {avail} (took {time.time() - t0:.2f}s)")

if avail:
    print("\nSending message to /assist...")
    msg = "Explain in two short sentences what Orange AI does."
    t1 = time.time()
    try:
        res = client.assist(message=msg, timeout=60.0)
        dur = time.time() - t1
        print(f"SUCCESS in {dur:.2f}s!")
        print("Response:", json.dumps(res, indent=2))
    except Exception as e:
        dur = time.time() - t1
        print(f"ERROR after {dur:.2f}s: {e}")
