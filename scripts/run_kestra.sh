#!/usr/bin/env bash
# Boot Kestra with its embedded database and run the recession-watch flow.
set -euo pipefail
cd "$(dirname "$0")/.."

# BuildKit's default provenance attestation publishes a manifest list.
# Compose on GitHub-hosted runners can then start the attestation blob,
# which fails with "exec /app/kestra: exec format error".
export BUILDX_NO_DEFAULT_ATTESTATIONS=1
if docker compose build --help 2>&1 | grep -q -- '--provenance'; then
  docker compose build --provenance=false
else
  docker compose build
fi
docker compose up -d --no-build
AUTH="admin@kestra.io:Admin1234"
echo "waiting for Kestra"
ready=0
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -u "$AUTH" "http://127.0.0.1:8080/api/v1/configs" || true)
  if [[ "$code" == "200" ]]; then
    ready=1
    break
  fi
  echo "health HTTP ${code:-none}"
  sleep 3
done
if [[ "$ready" != "1" ]]; then
  docker compose logs --tail 80
  echo "Kestra did not become ready" >&2
  exit 1
fi

curl -fsS -u "$AUTH" -X POST "http://127.0.0.1:8080/api/v1/flows" \
  -H "Content-Type: application/x-yaml" \
  --data-binary @kestra/flows/recession_watch.yml \
  || curl -fsS -u "$AUTH" -X PUT "http://127.0.0.1:8080/api/v1/flows/au.macro/recession_watch" \
    -H "Content-Type: application/x-yaml" \
    --data-binary @kestra/flows/recession_watch.yml

exec_json=$(curl -fsS -u "$AUTH" -X POST "http://127.0.0.1:8080/api/v1/executions/au.macro/recession_watch")
exec_id=$(python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" <<<"$exec_json")
echo "execution $exec_id"

for _ in $(seq 1 80); do
  state=$(curl -fsS -u "$AUTH" "http://127.0.0.1:8080/api/v1/executions/${exec_id}" \
    | python3 -c "import json,sys; body=json.load(sys.stdin); state=body.get('state') or {}; print(state.get('current') or state.get('name') or 'UNKNOWN')")
  echo "state $state"
  case "$state" in
    SUCCESS) exit 0 ;;
    FAILED|KILLED|CANCELLED)
      echo "---- task log ----"
      curl -fsS -u "$AUTH" "http://127.0.0.1:8080/api/v1/logs/${exec_id}" || true
      echo
      docker compose logs --tail 40
      exit 1
      ;;
  esac
  sleep 5
done
echo "execution timed out" >&2
exit 1
