#!/usr/bin/env python3
"""Push Firebase credentials to Railway environment variables."""
import json
import urllib.request
import urllib.error

RAILWAY_TOKEN = "3845f37d-4d58-4499-9a4f-eff00fdb29ad"
PROJECT_ID = "fabf0e60-9429-4a03-880b-72a5704"  # from session notes

# Read the Firebase service account
try:
    key = json.dumps(json.load(open('/sdcard/Download/nova-f83e3-86d2fc27598e.json')))
    print(f"Firebase key loaded: {len(key)} chars")
except Exception as e:
    print(f"Failed to read key: {e}")
    exit(1)

# Railway GraphQL API
url = "https://backboard.railway.app/graphql/v2"
headers = {
    "Authorization": f"Bearer {RAILWAY_TOKEN}",
    "Content-Type": "application/json"
}

# First get project details
query = '{"query": "{ me { projects { edges { node { id name environments { edges { node { id name } } } services { edges { node { id name } } } } } } } }"}'
req = urllib.request.Request(url, data=query.encode(), headers=headers)
try:
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2)[:2000])
except Exception as e:
    print(f"API call failed: {e}")
