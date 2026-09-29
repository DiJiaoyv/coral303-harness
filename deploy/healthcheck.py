#!/usr/bin/env python3
"""Docker HEALTHCHECK / 运维探活脚本。"""
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("HEALTH_URL", "http://127.0.0.1:7860/health")
TIMEOUT = int(os.environ.get("HEALTH_TIMEOUT", "5"))


def main() -> int:
    try:
        req = urllib.request.Request(URL, method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return 1
            body = resp.read().decode("utf-8", errors="replace")
            if "ok" not in body.lower():
                return 1
        return 0
    except (urllib.error.URLError, TimeoutError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
