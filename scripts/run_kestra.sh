#!/usr/bin/env bash
# Boot Kestra with its embedded database and run the recession-watch flow.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --build
echo "waiting for Kestra"
ready=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:8080/api/v1/configs" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 3
done
if [[ "$ready" != "1" ]]; then
  docker compose logs --tail 80
  echo "Kestra did not become ready" >&2
  exit 1
fi

import_flow() {
  docker compose exec -T kestra /app/kestra flow namespace update au.macro /work/kestra/flows \
    && return 0
  curl -fsS -X POST "http://127.0.0.1:8080/api/v1/flows" \
    -H "Content-Type: application/x-yaml" \
    --data-binary @kestra/flows/recession_watch.yml \
    && return 0
  return 1
}
import_flow

exec_json=$(curl -fsS -X POST "http://127.0.0.1:8080/api/v1/executions/au.macro/recession_watch")
exec_id=$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$exec_json")
echo "execution $exec_id"

for _ in $(seq 1 80); do
  state=$(curl -fsS "http://127.0.0.1:8080/api/v1/executions/${exec_id}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['state']['current'])")
  echo "state $state"
  case "$state" in
    SUCCESS) exit 0 ;;
    FAILED|KILLED|CANCELLED)
      docker compose logs --tail 40
      exit 1
      ;;
  esac
  sleep 5
done
echo "execution timed out" >&2
exit 1
