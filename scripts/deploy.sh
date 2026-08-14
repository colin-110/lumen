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

cd "$REPO"

# Base layers are tracked in the repo. The host-specific ones (instance
# sizing, the Caddy TLS front end) are not, and referencing them
# unconditionally made this script abort under `set -e` on any checkout that
# didn't have them — i.e. every clone, including a fresh provision of the box
# it is meant to deploy to. Include each overlay only if it is actually
# present, and say which ones were used.
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.free-tier.yml)
for overlay in docker-compose.ec2.yml docker-compose.caddy.yml; do
  if [ -f "$overlay" ]; then
    COMPOSE_FILES+=(-f "$overlay")
  else
    echo "==> note: $overlay not present, skipping"
  fi
done
echo "==> compose files: ${COMPOSE_FILES[*]}"

echo "==> fetching origin/main"
git fetch --quiet origin main
git reset --hard origin/main
echo "    now at $(git log --oneline -1)"

echo "==> building"
docker compose "${COMPOSE_FILES[@]}" build

echo "==> migrating"
# Before `up`, not after. Running migrations against an already-serving
# backend left a window where the new code was taking traffic against the old
# schema. The `migrate` service depends only on a healthy database, so it can
# run on its own — and `up` afterwards will wait on the same service having
# completed successfully, which makes this idempotent rather than duplicated.
#
# The previous readiness probe (`import app.db.session` inside the backend
# container) proved only that a module imported; it never touched Postgres.
docker compose "${COMPOSE_FILES[@]}" run --rm migrate

echo "==> starting"
docker compose "${COMPOSE_FILES[@]}" up -d

echo "==> pruning old images"
# Untagged layers only; keeps disk from filling on a 30GB volume after repeated
# rebuilds. Does not touch volumes, so no data is at risk.
docker image prune -f >/dev/null

echo "==> done"
