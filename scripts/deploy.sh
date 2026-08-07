#!/usr/bin/env bash
# Production deploy, run on the EC2 host.
#
# Invoked by .github/workflows/deploy.yml over SSM. SSM executes as root, but
# the checkout and the Docker state belong to ec2-user — git refuses to touch a
# repo owned by another user ("dubious ownership"), so the workflow re-enters as
# ec2-user and runs this. Keeping the steps in the repo (rather than inline in
# the workflow YAML) means they're reviewable in a diff and runnable by hand:
#
#   ssh ec2-user@<host> 'bash ~/lumen/scripts/deploy.sh'
set -euo pipefail

REPO="${REPO:-/home/ec2-user/lumen}"
COMPOSE_FILES=(
  -f docker-compose.yml
  -f docker-compose.free-tier.yml
  -f docker-compose.ec2.yml
  -f docker-compose.caddy.yml
)

cd "$REPO"

echo "==> fetching origin/main"
git fetch --quiet origin main
git reset --hard origin/main
echo "    now at $(git log --oneline -1)"

echo "==> building"
docker compose "${COMPOSE_FILES[@]}" build

echo "==> starting"
docker compose "${COMPOSE_FILES[@]}" up -d

echo "==> migrating"
# The backend needs to be accepting connections before alembic can run.
for _ in $(seq 1 30); do
  if docker compose "${COMPOSE_FILES[@]}" exec -T backend python -c "import app.db.session" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
docker compose "${COMPOSE_FILES[@]}" exec -T backend alembic upgrade head

echo "==> pruning old images"
# Untagged layers only; keeps disk from filling on a 30GB volume after repeated
# rebuilds. Does not touch volumes, so no data is at risk.
docker image prune -f >/dev/null

echo "==> done"
