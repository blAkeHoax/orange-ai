import sys
sys.path.insert(0, r"D:\Orange AI\Orange AI Desktop")
sys.path.insert(0, r"D:\Orange AI\Orange AI Tauri")
from runtime.runtime_adapter import handle_activity_get

data = handle_activity_get({})
print("LOGS:")
for l in data["logs"]:
    print(l)
print("\nCONVERSATIONS (last 5):")
for c in data["conversations"][:5]:
    print(c)
