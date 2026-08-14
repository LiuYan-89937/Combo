#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install.sh must run as root" >&2
  exit 1
fi

source_dir="${1:-}"
if [[ -z "${source_dir}" || ! -f "${source_dir}/pyproject.toml" ]]; then
  echo "usage: install.sh /path/to/combo_service/source" >&2
  exit 1
fi
if [[ ! -f /etc/combo-service.env ]]; then
  echo "/etc/combo-service.env must exist before installation" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends nginx python3 python3-pip python3-venv

if ! id combo_service >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/combo-service --shell /usr/sbin/nologin combo_service
fi

install -d -o root -g root -m 0755 /opt/combo-service
install -d -o combo_service -g combo_service -m 0750 /var/lib/combo-service
rm -rf /opt/combo-service/service.next
install -d -o root -g root -m 0755 /opt/combo-service/service.next
cp -a "${source_dir}/." /opt/combo-service/service.next/

if [[ ! -x /opt/combo-service/venv/bin/python ]]; then
  python3 -m venv /opt/combo-service/venv
fi
/opt/combo-service/venv/bin/python -m pip install --upgrade pip
/opt/combo-service/venv/bin/python -m pip install /opt/combo-service/service.next

rm -rf /opt/combo-service/service.previous
if [[ -d /opt/combo-service/service ]]; then
  mv /opt/combo-service/service /opt/combo-service/service.previous
fi
mv /opt/combo-service/service.next /opt/combo-service/service

install -o root -g root -m 0644 "${source_dir}/deploy/combo-service-api.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/deploy/combo-service-worker.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/deploy/combo-service-backup.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/deploy/combo-service-backup.timer" /etc/systemd/system/
nginx_source="${source_dir}/deploy/nginx-http.conf"
if [[ -f /etc/letsencrypt/live/liuyanai.top/fullchain.pem ]]; then
  nginx_source="${source_dir}/deploy/nginx.conf"
fi
install -o root -g root -m 0644 "${nginx_source}" /etc/nginx/sites-available/combo-service
ln -sfn /etc/nginx/sites-available/combo-service /etc/nginx/sites-enabled/combo-service
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
  install -d -o root -g root -m 0755 /var/www/combo-service
  # Atomic-ish swap: stage then rsync/copy over the live root.
  rm -rf /var/www/combo-service.next
  install -d -o root -g root -m 0755 /var/www/combo-service.next

  # New website bundles include the showcase built from the current desktop
  # frontend. Preserve a previous standalone showcase only for legacy bundles.
  if [[ ! -f "${frontend_dist}/app-showcase/showcase.html" ]]; then
    if [[ -d /var/www/combo-service/app-showcase ]]; then
      cp -a /var/www/combo-service/app-showcase /var/www/combo-service.next/
    fi
    if [[ -d /var/www/combo-service/assets ]]; then
      cp -a /var/www/combo-service/assets /var/www/combo-service.next/
    fi
  fi
  cp -a "${frontend_dist}/." /var/www/combo-service.next/
  rm -rf /var/www/combo-service.previous
  if [[ -d /var/www/combo-service && -n "$(ls -A /var/www/combo-service 2>/dev/null)" ]]; then
    mv /var/www/combo-service /var/www/combo-service.previous
  else
    rm -rf /var/www/combo-service
  fi
  mv /var/www/combo-service.next /var/www/combo-service
else
  echo "WARNING: no frontend bundle at ${frontend_dist}; serving API only." >&2
  install -d -o root -g root -m 0755 /var/www/combo-service
fi

chown root:combo_service /etc/combo-service.env
chmod 0640 /etc/combo-service.env
systemctl daemon-reload
nginx -t
systemctl enable --now nginx
systemctl enable combo-service-api.service combo-service-worker.service
systemctl restart combo-service-api.service combo-service-worker.service
systemctl reload nginx
systemctl enable --now combo-service-backup.timer
