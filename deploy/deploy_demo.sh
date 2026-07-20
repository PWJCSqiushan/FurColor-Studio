#!/usr/bin/env sh
set -eu
if [ "${CONFIRM_ISOLATED_DEPLOY:-}" != "yes" ]; then
  echo "Refusing deployment. First run deploy/audit_server.sh and review its output."
  echo "Then run with CONFIRM_ISOLATED_DEPLOY=yes from /opt/furcolor-demo."
  exit 2
fi
if [ "$(pwd)" != "/opt/furcolor-demo" ]; then echo "Refusing: expected working directory /opt/furcolor-demo"; exit 2; fi
if ! command -v docker >/dev/null 2>&1; then echo "Refusing: Docker is not installed"; exit 2; fi
if command -v ss >/dev/null 2>&1 && ss -lnt | awk '{print $4}' | grep -Eq '(^|:)8899$'; then
  if ! docker ps --format '{{.Names}}' | grep -qx 'furcolor-demo-web'; then
    echo "Refusing: port 8899 is already used by another service"; exit 2
  fi
fi
docker compose -p furcolor-demo -f docker-compose.demo.yml config >/dev/null
docker compose -p furcolor-demo -f docker-compose.demo.yml up -d --build
docker compose -p furcolor-demo -f docker-compose.demo.yml ps
echo "Demo is bound only to 127.0.0.1:8899. No firewall or reverse-proxy configuration was changed."
