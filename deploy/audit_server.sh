#!/usr/bin/env sh
set -eu
echo "FurColor read-only server audit"
echo "UTC: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "Host: $(hostname)"
echo "Disk:"
df -h /
echo "Listening TCP ports (8888 is an existing-service boundary and must remain untouched):"
if command -v ss >/dev/null 2>&1; then ss -lntp; else netstat -lntp 2>/dev/null || true; fi
echo "Docker availability:"
if command -v docker >/dev/null 2>&1; then
  docker version --format '{{.Server.Version}}' 2>/dev/null || true
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null || true
else
  echo "docker: not installed"
fi
echo "Reverse proxy configuration locations (names only):"
for d in /etc/nginx/conf.d /etc/nginx/sites-enabled /www/server/panel/vhost/nginx; do
  if [ -d "$d" ]; then find "$d" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null || true; fi
done
echo "FurColor target status:"
if [ -e /opt/furcolor-demo ]; then ls -ld /opt/furcolor-demo; else echo "/opt/furcolor-demo does not exist"; fi
echo "AUDIT COMPLETE — no files, firewall rules, containers, or services were changed."
