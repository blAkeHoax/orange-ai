import sys
import json
import time

sys.path.insert(0, r"D:\Orange AI\Orange AI Desktop")
sys.path.insert(0, r"D:\Orange AI\Orange AI Tauri")

import runtime.runtime_adapter as ra
ra._START_TIME = time.time()

health = ra.handle_system_health({})
print("SYSTEM HEALTH:")
print(json.dumps(health, indent=2))

from brain.api_client import OrangeAPIClient, DEFAULT_ORANGE_API_URL
c = OrangeAPIClient()
print("\nClient api_url:", c.api_url)
print("DEFAULT_ORANGE_API_URL:", DEFAULT_ORANGE_API_URL)
print("Client is_available:", c.is_available(timeout=0.5))
