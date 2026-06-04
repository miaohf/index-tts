#!/usr/bin/env bash
set -euo pipefail

REDIS_URL="redis://127.0.0.1:6379/0"

usage() {
  cat <<'EOF'
Clear IndexTTS queue and related Redis keys.

Usage:
  ./scripts/clear_tts_queue.sh [--redis-url <url>]

Examples:
  ./scripts/clear_tts_queue.sh
  ./scripts/clear_tts_queue.sh --redis-url redis://127.0.0.1:6379/0
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --redis-url)
      REDIS_URL="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${REDIS_URL}" ]]; then
  echo "--redis-url cannot be empty" >&2
  exit 2
fi

if ! command -v redis-cli >/dev/null 2>&1; then
  echo "redis-cli not found. Please install redis tools first." >&2
  exit 127
fi

PATTERNS=(
  "indextts:tts:job:*"
  "indextts:tts:request:*"
  "indextts:tts:audio:*"
  "indextts:tts:group:*"
  "indextts:tts:clientreq:*"
)

echo "Using Redis: ${REDIS_URL}"
echo "Before:"
for p in "${PATTERNS[@]}"; do
  c=$(redis-cli -u "${REDIS_URL}" --scan --pattern "${p}" | wc -l)
  echo "  ${p} ${c}"
done
echo "  indextts:tts:jobs $(redis-cli -u "${REDIS_URL}" EXISTS indextts:tts:jobs)"
echo "  indextts:tts:requests $(redis-cli -u "${REDIS_URL}" EXISTS indextts:tts:requests)"

redis-cli -u "${REDIS_URL}" DEL indextts:tts:jobs indextts:tts:requests >/dev/null
for p in "${PATTERNS[@]}"; do
  redis-cli -u "${REDIS_URL}" --scan --pattern "${p}" | xargs -r -n 200 redis-cli -u "${REDIS_URL}" DEL >/dev/null
done

echo "After:"
for p in "${PATTERNS[@]}"; do
  c=$(redis-cli -u "${REDIS_URL}" --scan --pattern "${p}" | wc -l)
  echo "  ${p} ${c}"
done
echo "  indextts:tts:jobs $(redis-cli -u "${REDIS_URL}" EXISTS indextts:tts:jobs)"
echo "  indextts:tts:requests $(redis-cli -u "${REDIS_URL}" EXISTS indextts:tts:requests)"
