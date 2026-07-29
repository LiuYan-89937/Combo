#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

source_dir="${1:-}"
if [[ -z "${source_dir}" || ! -f "${source_dir}/pyproject.toml" ]]; then
  echo "usage: install.sh /path/to/agent_hub/source" >&2
  exit 1
fi
if [[ ! -f /etc/fastagenthub.env ]]; then
  echo "/etc/fastagenthub.env must exist before installation" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends nginx python3 python3-pip python3-venv

if ! id fastagenthub >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/fastagenthub --shell /usr/sbin/nologin fastagenthub
fi

install -d -o root -g root -m 0755 /opt/fastagenthub
install -d -o fastagenthub -g fastagenthub -m 0750 /var/lib/fastagenthub
rm -rf /opt/fastagenthub/service.next
install -d -o root -g root -m 0755 /opt/fastagenthub/service.next
cp -a "${source_dir}/." /opt/fastagenthub/service.next/

if [[ ! -x /opt/fastagenthub/venv/bin/python ]]; then
  python3 -m venv /opt/fastagenthub/venv
fi
/opt/fastagenthub/venv/bin/python -m pip install --upgrade pip
/opt/fastagenthub/venv/bin/python -m pip install /opt/fastagenthub/service.next

rm -rf /opt/fastagenthub/service.previous
if [[ -d /opt/fastagenthub/service ]]; then
  mv /opt/fastagenthub/service /opt/fastagenthub/service.previous
fi
mv /opt/fastagenthub/service.next /opt/fastagenthub/service

install -o root -g root -m 0644 "${source_dir}/deploy/fastagenthub-api.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/deploy/fastagenthub-worker.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/deploy/fastagenthub-backup.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/deploy/fastagenthub-backup.timer" /etc/systemd/system/
nginx_source="${source_dir}/deploy/nginx-http.conf"
if [[ -f /etc/letsencrypt/live/liuyanai.top/fullchain.pem ]]; then
  nginx_source="${source_dir}/deploy/nginx.conf"
fi
install -o root -g root -m 0644 "${nginx_source}" /etc/nginx/sites-available/fastagenthub
ln -sfn /etc/nginx/sites-available/fastagenthub /etc/nginx/sites-enabled/fastagenthub
rm -f /etc/nginx/sites-enabled/default

# Static frontend (SPA). Prefer a prebuilt bundle (frontend/dist); otherwise
# build it in place when Node/npm are available. The web root is served by the
# nginx config above with an index.html fallback.
frontend_dist="${source_dir}/frontend/dist"
if [[ ! -d "${frontend_dist}" && -f "${source_dir}/frontend/package.json" ]] && command -v npm >/dev/null 2>&1; then
  echo "building frontend bundle..."
  ( cd "${source_dir}/frontend" && npm ci && npm run build )
fi
if [[ -d "${frontend_dist}" ]]; then
  install -d -o root -g root -m 0755 /var/www/fastagenthub
  # Atomic-ish swap: stage then rsync/copy over the live root.
  rm -rf /var/www/fastagenthub.next
  install -d -o root -g root -m 0755 /var/www/fastagenthub.next
  cp -a "${frontend_dist}/." /var/www/fastagenthub.next/
  rm -rf /var/www/fastagenthub.previous
  if [[ -d /var/www/fastagenthub && -n "$(ls -A /var/www/fastagenthub 2>/dev/null)" ]]; then
    mv /var/www/fastagenthub /var/www/fastagenthub.previous
  else
    rm -rf /var/www/fastagenthub
  fi
  mv /var/www/fastagenthub.next /var/www/fastagenthub
else
  echo "WARNING: no frontend bundle at ${frontend_dist}; serving API only." >&2
  install -d -o root -g root -m 0755 /var/www/fastagenthub
fi

chown root:fastagenthub /etc/fastagenthub.env
chmod 0640 /etc/fastagenthub.env
systemctl daemon-reload
nginx -t
systemctl enable --now nginx
systemctl enable fastagenthub-api.service fastagenthub-worker.service
systemctl restart fastagenthub-api.service fastagenthub-worker.service
systemctl reload nginx
systemctl enable --now fastagenthub-backup.timer
