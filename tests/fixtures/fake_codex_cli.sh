#!/usr/bin/env bash
# tests/fixtures/fake_codex_cli.sh
# Stands in for the real `codex exec` CLI in tests — never invoked in production,
# never makes a network call. Emits a minimal JSONL stream to stdout mimicking
# the normalized shape CodexDriver expects to parse, then exits 0.
set -euo pipefail
echo '{"type":"tool_call","tool":"read_file"}'
sleep 0.05

# Optional regression hook: if CODEX_TEST_GRANDCHILD_PID_FILE is set, spawn a
# detached grandchild that outlives this script and record its pid. It inherits
# this script's process group (bash without job control doesn't fork a new
# pgid for background jobs), so it stands in for the "orphaned grandchild"
# case CodexDriver._reap's process-group sweep is meant to catch. No effect on
# any test that leaves the env var unset.
if [[ -n "${CODEX_TEST_GRANDCHILD_PID_FILE:-}" ]]; then
  sleep 30 &
  echo $! > "$CODEX_TEST_GRANDCHILD_PID_FILE"
fi

echo '{"type":"completed","artifact":{"diff":"fake codex diff"}}'
exit 0
