"""Generate API keys for the 4 team members."""
import urllib.request
import json
import os

SECRET = os.environ.get("MCP_AUTH_ADMIN_SECRET", "d0761c54b488fb0732863fe73badf23f")

users = [
    ("lukas@straightforwardllc.us", "MCP-Admin", "Lukas"),
    ("ralphbenitez30@gmail.com", "MCP-Admin", "Ralph"),
    ("alamajacintg04@gmail.com", "MCP-Admin", "Jacint"),
    ("clidebacalla@gmail.com", "MCP-Admin", "Clarenz"),
]

for email, groups, label in users:
    data = json.dumps({"user_email": email, "user_groups": groups, "label": label}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/admin/generate-key",
        data=data,
        headers={"Content-Type": "application/json", "X-Admin-Secret": SECRET},
    )
    r = urllib.request.urlopen(req)
    result = json.loads(r.read())
    key = result.get("api_key", "ERROR")
    print(f"{label} ({email}): {key}")
