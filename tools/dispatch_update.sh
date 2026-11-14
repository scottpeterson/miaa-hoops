#!/bin/bash
# Start the dashboard's update runs on GitHub Actions from the Mac. launchd runs this every 10 minutes
# (com.scottpeterson.miaa-hoops-update). GitHub's own cron skips runs on busy days: on 2026-11-13 none of the
# eight evening runs between 22:00 and 01:30 UTC started, and Olivet's game at Wheaton (Ill.) never reached the
# page. A dispatched run starts within seconds.
#
# A run is due when the newest run started more than 25 minutes ago inside the workflow's evening windows
# (22:00 to 05:59 UTC in season, plus Saturday 16:00 to 21:59 UTC), or more than 5 hours 50 minutes ago at any
# other time (the four-times-a-day cron). Skips when a run is already queued or running: the workflow takes one
# run at a time.
#
# Before each run, the runner clone (~/projects/miaa-hoops-runner) reads the Presto pages that Presto's
# CloudFront refuses GitHub's runners (`fetch_data.py --presto`) and pushes data/presto_cache.json.
set -u
GH=/opt/homebrew/bin/gh
UV=/Users/scottpeterson/.local/bin/uv
REPO=scottpeterson/miaa-hoops
RUNNER=/Users/scottpeterson/projects/miaa-hoops-runner
hour=$((10#$(date -u +%H)))
month=$((10#$(date -u +%m)))
dow=$(date -u +%u)
window=0
case $month in
  11|12|1|2) if [ "$hour" -ge 22 ] || [ "$hour" -le 5 ] || { [ "$dow" = 6 ] && [ "$hour" -ge 16 ] && [ "$hour" -le 21 ]; }; then window=1; fi ;;
  3) [ "$hour" -le 5 ] && window=1 ;;
esac
[ $window = 1 ] && gap=1500 || gap=21000

runs=$("$GH" run list -R "$REPO" --workflow update.yml --limit 5 --json status,createdAt) || exit 1
due=$(/usr/bin/python3 - "$runs" "$gap" <<'PY'
import datetime, json, sys
runs, gap = json.loads(sys.argv[1]), int(sys.argv[2])
if any(r["status"] in ("queued", "in_progress", "pending") for r in runs):
    print("busy")
elif not runs:
    print("due")
else:
    newest = max(datetime.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) for r in runs)
    age = (datetime.datetime.now(datetime.timezone.utc) - newest).total_seconds()
    print("due" if age > gap else f"fresh {int(age // 60)}m")
PY
)
case $due in
  busy) echo "$(date -u '+%F %T') skipped: a run is already queued or running"; exit 0 ;;
  due) ;;
  *) exit 0 ;;
esac

# The Mac's copy of the Presto pages, pushed before the run starts so the runner's checkout has it.
if [ -d "$RUNNER/.git" ]; then
  (
    cd "$RUNNER" || exit 1
    git pull -q --rebase origin main || { echo "$(date -u '+%F %T') runner clone: pull failed"; exit 1; }
    "$UV" run --quiet python3 fetch_data.py --presto 2>&1 | tail -3
    if [ -n "$(git status --porcelain data/presto_cache.json)" ]; then
      git add data/presto_cache.json
      git commit -q -m "Presto cache $(date -u '+%F %H:%M UTC')"
      git pull -q --rebase origin main && git push -q origin HEAD:main && echo "$(date -u '+%F %T') pushed the Presto cache"
    fi
  )
fi

"$GH" workflow run update.yml -R "$REPO" && echo "$(date -u '+%F %T') dispatched an update run (window=$window)"
exit 0
