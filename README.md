# stagehand-sweeps — cloud keepalive for the dual-track pipeline

Runs discovery while Preston's computer is off. Deliberately dumb: fetch public
pages, commit files. All parsing, fit-scoring, and drafting happens locally in
Stagehand. No secrets, no tokens, no LLM calls here.

## What runs (daily, 05:30 CT via GitHub Actions)
- `discover.py` → `discovered/discovered-<date>.json` — fresh rows from the
  speedyapply + vanshb03 GitHub trackers (CS internships).
- `theatre_snapshot.py` → `snapshots/<source>-<date>.html` — raw HTML of the
  theatre sources in `sources.json` (BroadwayWorld, OffStageJobs, convention
  sites…). Pruned after 14 days.

## How Stagehand consumes it
The 06:45 morning refresh fetches (via web_fetch, which CAN reach
raw.githubusercontent.com even though the sandbox shell can't):
  `https://raw.githubusercontent.com/PrestonScott05/stagehand-sweeps/master/discovered/discovered-<date>.json`
and the day's snapshots, then merges/parses locally. Machine off for N days →
next wake processes N days of files. Nothing is lost, only delayed.

## Preston's one-time setup (~5 minutes)
1. Create a **private** GitHub repo named `stagehand-sweeps`.
2. Copy this folder's contents in and push (`sources.json` is included).
3. Repo → Actions tab → enable workflows. Optionally hit "Run workflow" once
   to verify — you should see a commit with `discovered/` + `snapshots/`.
4. Tell Claude the repo is up (give the `<user>/stagehand-sweeps` path) so the
   morning task starts pulling from it.

Until this exists, the pipeline still works — the morning refresh just does
discovery locally via web_fetch and misses days when the computer is off.
