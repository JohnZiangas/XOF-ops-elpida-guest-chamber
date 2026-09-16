#!/usr/bin/env bash
# tools/watchtower.sh — call the Watchtower Elpida API (HF Space:
# z65nik/elpida-api). Stage 3a + 3b of the chamber's apprenticeship-gate
# integration named in the brain's 2026-05-09 from_brain.md entry: the
# chamber can now optionally invoke Watchtower's audit / scan endpoints
# from session or from CI.
#
# Constitutional context: this tool gives the chamber-side agent a way to
# route a question to the architecture's parliament (via /v1/audit) or
# scan arbitrary text for axiom signatures (via /scan) — both of which
# return brain-side output. The chamber transmits what comes back; it
# does NOT paraphrase the verdict or pretend to be the parliament.
# A2 (Non-Deception): the JSON is the canonical record; this tool just
# fetches it.
#
# Subcommands:
#   health                          GET  /health     (no auth)
#   domains                         GET  /domains    (no auth)
#   audit "<action>" [quick|full]   POST /v1/audit   (requires ELPIDA_API_KEY)
#   scan  "<text>"                  POST /scan       (requires ELPIDA_API_KEY)
#
# The ELPIDA_API_KEY for the chamber is in this repo's GHA secrets (added
# by the architect 2026-05-12). It is NOT in the Codespace's shell env by
# default. To use audit/scan locally:
#   export ELPIDA_API_KEY=<your-key-value>
# In CI, expose the GHA secret as an env var in the workflow step.
#
# Dependencies: curl, jq, python3 (json.tool pretty-printer). All standard
# on the chamber Codespace runner.

set -euo pipefail

API_BASE="https://z65nik-elpida-api.hf.space"

require_key() {
  if [ -z "${ELPIDA_API_KEY:-}" ]; then
    cat <<EOF >&2
ERROR: ELPIDA_API_KEY not set. The audit and scan endpoints require it.
  Locally: export ELPIDA_API_KEY=<key>
  In CI:   expose the GHA secret of the same name as a workflow env var.
The key is in this repo's GitHub Actions secrets (added 2026-05-12).
EOF
    exit 1
  fi
}

# Run a request and pretty-print the JSON. On HTTP error, print the body
# and the status code to stderr, then exit non-zero. A2 discipline: never
# hide the API's actual response.
run() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local tmp http_code
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' RETURN

  if [ -n "$body" ]; then
    http_code=$(curl -s --max-time 60 -o "$tmp" -w "%{http_code}" \
      -X "$method" \
      -H "Content-Type: application/json" \
      -H "X-API-Key: ${ELPIDA_API_KEY:-}" \
      -d "$body" \
      "$url")
  else
    http_code=$(curl -s --max-time 20 -o "$tmp" -w "%{http_code}" "$url")
  fi

  if [ "$http_code" -ge 400 ] 2>/dev/null; then
    echo "HTTP $http_code from $url" >&2
    if [ -s "$tmp" ]; then
      python3 -m json.tool < "$tmp" 2>/dev/null || cat "$tmp"
    fi
    exit 1
  fi

  python3 -m json.tool < "$tmp" 2>/dev/null || cat "$tmp"
}

cmd="${1:-help}"

case "$cmd" in
  health)
    run GET "$API_BASE/health"
    ;;
  domains)
    run GET "$API_BASE/domains"
    ;;
  audit)
    require_key
    action="${2:-}"
    depth="${3:-quick}"
    if [ -z "$action" ]; then
      echo "usage: $0 audit \"<action>\" [quick|full]" >&2
      exit 1
    fi
    if [ "$depth" != "quick" ] && [ "$depth" != "full" ]; then
      echo "ERROR: depth must be 'quick' or 'full' (got: $depth)" >&2
      exit 1
    fi
    body=$(jq -nc --arg a "$action" --arg d "$depth" '{action: $a, depth: $d}')
    run POST "$API_BASE/v1/audit" "$body"
    ;;
  scan)
    require_key
    text="${2:-}"
    if [ -z "$text" ]; then
      echo "usage: $0 scan \"<text>\"" >&2
      exit 1
    fi
    body=$(jq -nc --arg t "$text" '{text: $t, depth: "quick"}')
    run POST "$API_BASE/scan" "$body"
    ;;
  help|--help|-h)
    cat <<EOF
tools/watchtower.sh — call the Watchtower Elpida API

Usage:
  $0 health                          Smoke-test the API. No auth.
  $0 domains                         List the 17 domains + axioms. No auth.
  $0 audit "<action>" [quick|full]   Constitutional audit of a proposed action.
                                       'quick' = heuristic, 'full' = LLM-powered.
                                       Requires ELPIDA_API_KEY.
  $0 scan "<text>"                   Scan text for axiom signatures.
                                       Requires ELPIDA_API_KEY.

API base: $API_BASE
EOF
    ;;
  *)
    echo "ERROR: unknown subcommand '$cmd'" >&2
    echo "Try: $0 help" >&2
    exit 1
    ;;
esac
