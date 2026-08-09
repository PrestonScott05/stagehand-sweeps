#!/usr/bin/env python3
"""
Theatre source snapshotter — GitHub Actions leg (full network there).

Fetches each source URL from sources.json and saves the raw HTML to
snapshots/<name>-<date>.html. Deliberately dumb: no parsing, no LLM, no
secrets, public pages only. The local Stagehand morning run pulls these
snapshots (or, when the machine is online, fetches sources directly via
web_fetch) and Claude parses them into theatre-queue candidates.

Also prunes snapshots older than 14 days to keep the repo small.
"""

import json
import re
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
SOURCES = HERE / "sources.json"
SNAP = HERE / "snapshots"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def main():
    cfg = json.loads(SOURCES.read_text())
    SNAP.mkdir(exist_ok=True)
    today = date.today().isoformat()
    ok, fail = 0, 0
    for s in cfg["sources"]:
        if s.get("login_walled") or s.get("cloud") is False:
            continue  # local-leg-only sources (JS-walled or blocks datacenter IPs)
        name = re.sub(r"[^a-z0-9]+", "-", s["name"].lower()).strip("-")
        try:
            req = urllib.request.Request(s["url"], headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            (SNAP / f"{name}-{today}.html").write_bytes(body)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"[snapshot] FAIL {s['name']}: {e}", file=sys.stderr)
            fail += 1
        time.sleep(2)  # be polite

    cutoff = (date.today() - timedelta(days=14)).isoformat()
    for p in SNAP.glob("*.html"):
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.html$", p.name)
        if m and m.group(1) < cutoff:
            p.unlink()

    print(f"[snapshot] {ok} saved, {fail} failed")


if __name__ == "__main__":
    main()
