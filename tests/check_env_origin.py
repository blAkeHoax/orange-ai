import os
import sys

print("Initial os.environ ORANGE_API_URL:", os.environ.get("ORANGE_API_URL"))

sys.path.insert(0, r"D:\Orange AI\Orange AI Desktop")
import brain.paths
print("brain.paths.__file__:", brain.paths.__file__)
root = brain.paths.get_project_root()
print("get_project_root():", root)
print(".env in root:", os.path.join(root, ".env"), "exists?", os.path.exists(os.path.join(root, ".env")))

# Also check source root
src_root = r"D:\Orange AI\Orange AI Desktop"
print(".env in Desktop workspace:", os.path.join(src_root, ".env"), "exists?", os.path.exists(os.path.join(src_root, ".env")))

import brain.api_client
print("api_client DEFAULT_ORANGE_API_URL:", brain.api_client.DEFAULT_ORANGE_API_URL)
print("api_client._env_path:", getattr(brain.api_client, "_env_path", None))
print("os.environ after api_client import:", os.environ.get("ORANGE_API_URL"))

c = brain.api_client.OrangeAPIClient()
print("c.api_url:", c.api_url)
