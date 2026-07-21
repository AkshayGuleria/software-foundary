#!/usr/bin/env bash
# tests/fixtures/fake_codex_cli.sh
# Stands in for the real `codex exec` CLI in tests — never invoked in production,
# never makes a network call. Emits a minimal JSONL stream to stdout mimicking
# the normalized shape CodexDriver expects to parse, then exits 0.
set -euo pipefail
echo '{"type":"tool_call","tool":"read_file"}'
sleep 0.05
echo '{"type":"completed","artifact":{"diff":"fake codex diff"}}'
exit 0
