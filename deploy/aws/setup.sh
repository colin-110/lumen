#!/usr/bin/env bash
# Provision or update Lumen on the EC2 host created by deploy/aws/lumen.yml.
#
# First boot: run by the instance's user data. Every later deploy: run again
# over SSM (see the README's "Deploying to AWS"). Safe to re-run: swap,
# Docker and secrets are only created once; code is pulled and rebuilt.
set -euo pipefail
exec > >(tee -a /var/log/lumen-setup.log) 2>&1
echo "=== lumen setup $(date -u +%FT%TZ)"

REPO_DIR=/opt/lumen
CONF_DIR=/etc/lumen
# shellcheck disable=SC1091
source "$CONF_DIR/host.env"   # LUMEN_DOMAIN, AWS_REGION (written by user data)

# --- 2 GB swap: headroom for ingestion peaks on a 2 GB instance ----------
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10 && echo 'vm.swappiness=10' > /etc/sysctl.d/99-lumen.conf
fi

# --- Docker and the AWS CLI ----------------------------------------------
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
command -v aws >/dev/null || snap install aws-cli --classic

param() {  # print an SSM parameter's value, or nothing if it doesn't exist
  aws ssm get-parameter --region "$AWS_REGION" --name "$1" --with-decryption \
    --query Parameter.Value --output text 2>/dev/null || true
}

# --- code ----------------------------------------------------------------
git -C "$REPO_DIR" pull --ff-only

# --- secrets: generated once, kept on the host ---------------------------
if [ ! -f "$CONF_DIR/secrets.env" ]; then
  rand() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
  umask 077
  cat > "$CONF_DIR/secrets.env" <<EOF
SECRET_KEY=$(rand 64)
POSTGRES_PASSWORD=$(rand 32)
FIRST_SUPERUSER_PASSWORD=$(rand 24)
METRICS_TOKEN=$(rand 32)
EOF
fi
# shellcheck disable=SC1091
source "$CONF_DIR/secrets.env"

GEMINI_API_KEY=$(param /lumen/GEMINI_API_KEY)
CORS_ORIGINS=$(param /lumen/CORS_ORIGINS)
[ -n "$GEMINI_API_KEY" ] || echo "WARNING: /lumen/GEMINI_API_KEY is not set; chat will not answer."

umask 077
cat > "$REPO_DIR/backend/.env" <<EOF
ENVIRONMENT=production
LOG_JSON=true
SECRET_KEY=$SECRET_KEY
METRICS_TOKEN=$METRICS_TOKEN
ALLOW_OPEN_REGISTRATION=true
TRUSTED_PROXY_HEADERS=true
BACKEND_CORS_ORIGINS=$CORS_ORIGINS

FIRST_ORG_NAME=Acme Corp
FIRST_SUPERUSER_EMAIL=admin@lumen.dev
FIRST_SUPERUSER_PASSWORD=$FIRST_SUPERUSER_PASSWORD
DEMO_USER_EMAIL=demo@lumen.dev
DEMO_USER_PASSWORD=try-lumen-demo
SEED_DEMO_DOCUMENTS=true

GEMINI_API_KEY=$GEMINI_API_KEY
PRIMARY_MODEL=gemini/gemini-flash-lite-latest
FALLBACK_MODELS=gemini/gemini-3.6-flash

POSTGRES_USER=postgres
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=lumen
EOF
# Compose-level interpolation: the db service and ENVIRONMENT override.
cat > "$REPO_DIR/.env" <<EOF
ENVIRONMENT=production
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=lumen
LUMEN_DOMAIN=$LUMEN_DOMAIN
EOF

# --- build and start -----------------------------------------------------
cd "$REPO_DIR"
COMPOSE=(docker compose -f docker-compose.yml -f deploy/aws/docker-compose.aws.yml)
"${COMPOSE[@]}" up -d --build --remove-orphans

for _ in $(seq 1 90); do
  [ "$("${COMPOSE[@]}" ps backend --format '{{.Health}}')" = healthy ] && break
  sleep 5
done
"${COMPOSE[@]}" exec -T backend python -m scripts.seed

# Admin password, readable later with:
#   aws ssm get-parameter --name /lumen/ADMIN_PASSWORD --with-decryption
if [ -z "$(param /lumen/ADMIN_PASSWORD)" ]; then
  aws ssm put-parameter --region "$AWS_REGION" --name /lumen/ADMIN_PASSWORD \
    --type SecureString --value "$FIRST_SUPERUSER_PASSWORD" >/dev/null
fi

docker image prune -f >/dev/null
echo "=== lumen ready at https://$LUMEN_DOMAIN"
