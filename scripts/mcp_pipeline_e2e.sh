#!/usr/bin/env bash
# Phase 4 exit gate, end to end: an agent (the MCP client in mcp/tests/smoke_pipeline.py) explores, proposes a Maine
# view, writes the manifest and gets the apply command; this script plays the person who approves it and runs
# ./mapgen apply; the agent then checks the published project. Everything it created is removed afterwards.
set -uo pipefail
cd "$(dirname "$0")/.."
SLUG=zz-mcp-downeast-towns
VIEW=pub.zz_mcp_downeast_towns__towns
DC=(docker compose)
LOG=$(mktemp)
fails=0

cleanup() {
  rm -rf "projects/$SLUG"
  python3 - "$SLUG" <<'EOF'
import json, sys
p = "projects/index.json"; d = json.load(open(p))
if sys.argv[1] in d["projects"]:
    d["projects"].remove(sys.argv[1]); open(p, "w").write(json.dumps(d, indent=2) + "\n")
EOF
  "${DC[@]}" exec -T postgis sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -qc \"DROP VIEW IF EXISTS $VIEW; DELETE FROM app.projects WHERE slug = '$SLUG';\"" >/dev/null 2>&1
  rm -f "$LOG"
}
trap cleanup EXIT
cleanup
LOG=$(mktemp)

out=$("${DC[@]}" run --rm -T --no-deps mcp-pipeline python tests/smoke_pipeline.py propose 2>/dev/null)
rc=$?
echo "$out" | grep -E '^(PASS|FAIL)'
cmd=$(echo "$out" | grep -E '^\./mapgen apply ' | tail -1)
[[ $rc == 0 && $cmd == "./mapgen apply $SLUG" ]] || { echo "FAIL  the agent did not get to an apply command"; exit 1; }

echo "      (approved) $cmd"
if $cmd > "$LOG" 2>&1; then echo "PASS  ./mapgen apply ran"; else echo "FAIL  ./mapgen apply"; tail -5 "$LOG"; exit 1; fi

"${DC[@]}" run --rm -T --no-deps mcp-pipeline python tests/smoke_pipeline.py check 2>/dev/null | grep -E '^(PASS|FAIL)'
[[ ${PIPESTATUS[0]} == 0 ]] || fails=1
exit $fails
