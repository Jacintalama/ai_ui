"""What each user actually sees in their model picker.

Run before and after flipping BYPASS_MODEL_ACCESS_CONTROL. The failure being
guarded against is silent and total: a non-admin opens the picker and it is
empty, with nothing logged anywhere.

Usage, inside the mcp-proxy container (it has PyJWT; tasks does not):
    docker exec -e PROBE_SECRET=... mcp-proxy python /tmp/model_visibility_probe.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("PROBE_BASE", "https://ai-ui.coolestdomain.win")
# Cloudflare 1010-blocks urllib's default User-Agent on this domain.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def models_for(token):
    req = urllib.request.Request(BASE + "/api/models", headers={
        "Authorization": "Bearer " + token, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    data = body.get("data", body if isinstance(body, list) else [])
    return sorted(m.get("id") for m in data)


def main():
    out = {}
    for pair in os.environ["PROBE_TOKENS"].split(";"):
        label, token = pair.split("=", 1)
        try:
            ids = models_for(token)
            out[label] = ids
            print("%-30s %3d models" % (label, len(ids)))
        except urllib.error.HTTPError as e:
            print("%-30s HTTP %s" % (label, e.code))
            out[label] = None
    path = os.environ.get("PROBE_OUT", "/tmp/model_visibility.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1)
    print("written to", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
