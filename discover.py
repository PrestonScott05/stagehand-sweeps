#!/usr/bin/env python3
"""
CS internship discovery — fetch public GitHub tracker READMEs, diff against
what we've already surfaced, emit a discovered-<date>.json for sweep_merge.py.

Usage:
  python recruiting/discover.py                # normal daily run
  python recruiting/discover.py --max-age 14   # widen the age window
  python recruiting/discover.py --out DIR      # write discovered file elsewhere
                                               # (used by the GitHub Actions leg)

Sources (public, no auth):
  - speedyapply/2027-SWE-College-Jobs   (README.md markdown tables, HTML anchors)
  - vanshb03/Summer2027-Internships     (README.md markdown tables)

What this does (deterministic, safe to re-run):
  1. Fetch each source README.
  2. Parse table rows -> candidate postings (company, role, location, comp,
     apply_url, age_days, source).
  3. Drop rows older than --max-age days (default 8) — the daily diff window.
  4. Drop rows whose normalized URL is already in cs-scout-seen.json.
  5. Write recruiting/data/pipeline/raw/discovered-<date>.json and append the
     new URLs to cs-scout-seen.json.

The output is CANDIDATES — the sweep session (Claude) curates before merging
(geography/season/fit), then calls sweep_merge.py with --status new|ready.

HARD RULES: never writes recruiting/inputs/. Never submits anything.
"""

import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
SEEN_PATH = ROOT / "recruiting" / "data" / "cs-scout-seen.json"
RAW_DIR = ROOT / "recruiting" / "data" / "pipeline" / "raw"

SOURCES = [
    ("speedyapply",
     "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md"),
    ("vanshb03",
     "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/main/README.md"),
]

UA = {"User-Agent": "Mozilla/5.0 (stagehand-sweep; personal job tracker)"}

HREF_RE = re.compile(r'href="([^"]+)"')
MD_LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
TAG_RE = re.compile(r"<[^>]+>")
AGE_RE = re.compile(r"^(\d+)\s*(d|h|mo)$", re.I)


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_cell(cell):
    """Plain text of a table cell (drop tags, markdown links keep their text)."""
    cell = MD_LINK_RE.sub(lambda m: m.group(1), cell)
    cell = TAG_RE.sub("", cell)
    return cell.replace("**", "").replace("↳", "").strip()


def cell_url(cell):
    """First URL in a cell — html href wins, then markdown link."""
    m = HREF_RE.search(cell)
    if m:
        return m.group(1)
    m = MD_LINK_RE.search(cell)
    if m:
        return m.group(2)
    return None


def parse_age_days(text):
    m = AGE_RE.match(text.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == "h":
        return 0
    if unit == "mo":
        return n * 30
    return n


def norm_url(u):
    if not u:
        return ""
    u = u.strip().split("#")[0].split("?utm")[0].rstrip("/")
    return u.lower()


def parse_readme(name, text):
    """Parse markdown-table rows into candidate dicts. Tolerant of both
    speedyapply (HTML anchors, Age column) and vanshb03 (md links, Date col)."""
    out = []
    last_company = None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        header = strip_cell(cells[0]).lower()
        if header in ("company", ":---", "---") or set(cells[0]) <= {"-", ":", " "}:
            continue
        company = strip_cell(cells[0])
        if company in ("", "↳"):
            company = last_company
        else:
            last_company = company
        role = strip_cell(cells[1])
        location = strip_cell(cells[2]) if len(cells) > 2 else ""
        # apply url: prefer a non-company-homepage link from any cell right of role
        url = None
        for c in cells[3:] + [cells[1]]:
            u = cell_url(c)
            if u and "i.imgur.com" not in u:
                url = u
                break
        if not url:
            continue
        comp = ""
        age_days = None
        for c in cells[3:]:
            t = strip_cell(c)
            if t.startswith("$") and not comp:
                comp = t
            a = parse_age_days(t)
            if a is not None:
                age_days = a
        if not company or not role:
            continue
        if "intern" not in role.lower() and "co-op" not in role.lower() \
                and "coop" not in role.lower() and "analyst" not in role.lower():
            continue
        out.append({
            "company": company,
            "role": role,
            "location": location,
            "comp": comp or None,
            "apply_url": url,
            "posted_age_days_at_scrape": age_days,
            "source": name,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=int, default=8,
                    help="drop rows older than this many days (default 8)")
    ap.add_argument("--out", default=None,
                    help="output dir (default recruiting/data/pipeline/raw)")
    ap.add_argument("--no-seen-update", action="store_true",
                    help="don't append to cs-scout-seen.json (Actions leg uses this)")
    ap.add_argument("--from", dest="from_files", action="append", default=[],
                    metavar="NAME=PATH",
                    help="parse a locally saved README/rows file instead of fetching "
                         "(local leg: Cowork sandbox cannot reach github.com; Claude "
                         "fetches via web_fetch and passes the saved file here)")
    args = ap.parse_args()

    seen = {"_note": "Job IDs/URLs already surfaced to Preston. Career Scout skips these on future runs.",
            "seen": [], "last_run": None}
    if SEEN_PATH.exists():
        seen = json.loads(SEEN_PATH.read_text())
    seen_set = {norm_url(u) for u in seen.get("seen", [])}

    if args.from_files:
        sources = []
        for spec in args.from_files:
            name, _, path = spec.partition("=")
            sources.append((name, ("file", path)))
    else:
        sources = [(n, ("url", u)) for n, u in SOURCES]

    candidates, errors = [], []
    for name, (kind, loc) in sources:
        try:
            text = Path(loc).read_text() if kind == "file" else fetch(loc)
            rows = parse_readme(name, text)
            fresh = [r for r in rows
                     if (r["posted_age_days_at_scrape"] is None
                         or r["posted_age_days_at_scrape"] <= args.max_age)]
            new = [r for r in fresh if norm_url(r["apply_url"]) not in seen_set]
            print(f"[discover] {name}: {len(rows)} rows, {len(fresh)} within "
                  f"{args.max_age}d, {len(new)} unseen", file=sys.stderr)
            candidates.extend(new)
        except Exception as e:  # noqa: BLE001 — a dead source must not kill the run
            errors.append({"source": name, "error": str(e)})
            print(f"[discover] ERROR {name}: {e}", file=sys.stderr)

    # de-dupe within the run
    by_url = {}
    for c in candidates:
        by_url.setdefault(norm_url(c["apply_url"]), c)
    candidates = list(by_url.values())

    today = date.today().isoformat()
    out_dir = Path(args.out) if args.out else RAW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"discovered-{today}.json"
    payload = {"scraped": today, "sources_ok": [s for s, _ in SOURCES
                                               if s not in [e["source"] for e in errors]],
               "source_errors": errors, "candidates": candidates}
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"[discover] wrote {out_path} — {len(candidates)} candidates, "
          f"{len(errors)} source errors", file=sys.stderr)

    if not args.no_seen_update:
        seen["seen"] = sorted(seen_set | {norm_url(c["apply_url"]) for c in candidates})
        seen["last_run"] = today
        SEEN_PATH.write_text(json.dumps(seen, indent=2))

    print(str(out_path))


if __name__ == "__main__":
    main()
