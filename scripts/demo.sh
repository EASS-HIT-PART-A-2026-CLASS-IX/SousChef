#!/usr/bin/env bash
#
# SousChef EX3 demo — walks a grader through the app in under 2 minutes.
# Run from the repo root:  bash scripts/demo.sh
#
set -euo pipefail

API="${API_BASE_URL:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USERNAME:-admin}"
ADMIN_PW="${ADMIN_PASSWORD:-admin}"   # plaintext; backend stores ADMIN_PASSWORD_HASH
BACKEND_PID=""

header() { printf "\n\033[1;36m== %s ==\033[0m\n" "$1"; }

cleanup() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    header "Cleanup: stopping backend (pid ${BACKEND_PID})"
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ -z "${ADMIN_PASSWORD_HASH:-}" ]]; then
  echo "ERROR: ADMIN_PASSWORD_HASH is not set. The auth step will fail." >&2
  echo "Generate one and add it to .env / your shell, e.g.:" >&2
  echo "  cd backend && python -c \"from app import auth; print(auth.hash_password('admin'))\"" >&2
  echo "It must be the hash of ADMIN_PASSWORD (default 'admin')." >&2
  exit 1
fi

header "1/6  Starting the backend (uvicorn, detached)"
( cd backend && source .venv/bin/activate && \
  exec uvicorn app.main:app --port 8000 >/tmp/souschef-demo.log 2>&1 ) &
BACKEND_PID=$!
echo "backend pid: ${BACKEND_PID}  (logs: /tmp/souschef-demo.log)"

header "2/6  Waiting for backend health"
for i in $(seq 1 30); do
  if curl -fsS "${API}/recipes" >/dev/null 2>&1; then
    echo "backend healthy after ${i}s"; break
  fi
  if [[ "${i}" -eq 30 ]]; then echo "backend did not become healthy"; exit 1; fi
  sleep 1
done

header "3/6  Smoke test: create a recipe"
CREATED=$(curl -fsS -X POST "${API}/recipes" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Demo Shakshuka","category":"ארוחת בוקר"}')
echo "${CREATED}"
RECIPE_ID=$(echo "${CREATED}" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")

header "4/6  List recipes (should include the new one)"
curl -fsS "${API}/recipes" | python3 -m json.tool | head -n 20

header "5/6  Auth: obtain a JWT and delete via the protected route"
TOKEN=$(curl -fsS -X POST "${API}/token" \
  -d "username=${ADMIN_USER}&password=${ADMIN_PW}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "got token: ${TOKEN:0:24}..."
echo "deleting recipe ${RECIPE_ID} (admin only):"
curl -fsS -o /dev/null -w "DELETE status: %{http_code}\n" \
  -X DELETE "${API}/recipes/${RECIPE_ID}" \
  -H "Authorization: Bearer ${TOKEN}"

header "6/6  Frontend"
echo "Streamlit UI runs separately. Start it with:"
echo "    cd frontend && streamlit run main.py"
echo "Then open http://localhost:8501"

header "Demo complete"
