import os
import json, urllib.request, urllib.parse

RAILWAY_TOKEN = os.environ.get("RAILWAY_TOKEN", "")

# Read Firebase key
key = json.dumps(json.load(open('/sdcard/Download/nova-f83e3-86d2fc27598e.json')))
print(f"Key loaded: {len(key)} chars")

url = "https://backboard.railway.app/graphql/v2"
if not RAILWAY_TOKEN:
    raise SystemExit("Set RAILWAY_TOKEN in the environment")

headers = {
    "Authorization": f"Bearer {RAILWAY_TOKEN}",
    "Content-Type": "application/json"
}

# Get project/service/env IDs
query = json.dumps({"query": "{ me { projects { edges { node { id name environments { edges { node { id name } } } services { edges { node { id name } } } } } } } }"})
req = urllib.request.Request(url, data=query.encode(), headers=headers, method="POST")
resp = urllib.request.urlopen(req, timeout=15)
data = json.loads(resp.read())
print(json.dumps(data, indent=2)[:3000])
