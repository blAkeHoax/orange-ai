import sys
import json
import time

sys.path.insert(0, r"D:\Orange AI\Orange AI Desktop")

from brain.api_client import OrangeAPIClient

def probe():
    client = OrangeAPIClient()
    print("API Endpoint:", client.api_url)
    print("Checking availability...")
    is_avail = client.is_available(timeout=2.0)
    print("is_available:", is_avail)

    if not is_avail:
        print("API is not available!")
        return

    print("\nSending test message to /assist...")
    msg = "Explain in two short sentences what Orange AI does."
    t0 = time.time()
    try:
        res = client.assist(message=msg, timeout=60.0)
        dur = time.time() - t0
        print(f"Response received in {dur:.2f}s:")
        print(json.dumps(res, indent=2))
    except Exception as e:
        dur = time.time() - t0
        print(f"Failed after {dur:.2f}s: {e}")

if __name__ == "__main__":
    probe()
