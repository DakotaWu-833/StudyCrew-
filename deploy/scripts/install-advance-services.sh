#!/usr/bin/env bash
# Install the reviewed advance services after the host, database, SMTP and TLS exist.
set -Eeuo pipefail

usage() {
    echo "Usage: sudo bash $0 HOST [--enable-backups] [--enable-health]" >&2
    echo "HOST is the existing certificate's DNS name or IPv4 address." >&2
}
fail() { echo "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail "Run this script with sudo."
[[ $# -ge 1 ]] || { usage; exit 2; }
host=$1
shift
enable_backups=false
enable_health=false
for option in "$@"; do
    case ${option} in
        --enable-backups) enable_backups=true ;;
        --enable-health) enable_health=true ;;
        *) usage; fail "Unknown option: ${option}" ;;
    esac
done
[[ ${host} =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || fail "Use a DNS name or IPv4 address, without a scheme, port or path."
[[ ${host} != *..* && ${#host} -le 253 ]] || fail "Invalid host."

app=/srv/studycrew/app
environment_file=/etc/studycrew/studycrew.env
certificate=/etc/letsencrypt/live/${host}/fullchain.pem
private_key=/etc/letsencrypt/live/${host}/privkey.pem
management=${app}/deploy/scripts/run-production-management.sh
[[ -f ${management} ]] || fail "Install the reviewed release under ${app} first."
[[ -x /srv/studycrew/venv/bin/uwsgi ]] || fail "Install requirements/production.txt in the production virtual environment first."
[[ -f ${environment_file} && ! -L ${environment_file} ]] || fail "Create the protected production environment file first."
[[ $(stat -c %u "${environment_file}") == 0 ]] || fail "The production environment file must be root-owned."
case $(stat -c %a "${environment_file}") in
    600|640) ;;
    *) fail "The production environment file must have mode 0600 or 0640." ;;
esac
[[ -r ${certificate} && -r ${private_key} ]] || fail "Obtain the matching TLS certificate before running this installer."
[[ ! -e /etc/nginx/sites-enabled/default && ! -L /etc/nginx/sites-enabled/default ]] || fail "Move the stock sites-enabled/default link outside sites-enabled, preserving it for rollback, then retry."
for command in nginx systemctl openssl python3 install cp mktemp; do
    command -v "${command}" >/dev/null || fail "Required host command missing: ${command}"
done
openssl x509 -in "${certificate}" -noout -checkend 0 >/dev/null
if [[ ${host} =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    openssl x509 -in "${certificate}" -noout -checkip "${host}" >/dev/null
else
    openssl x509 -in "${certificate}" -noout -checkhost "${host}" >/dev/null
fi

# These checks import secrets only through the existing protected helper.
# They neither migrate the database nor create demo users.
bash "${management}" check --deploy --fail-level WARNING
bash "${management}" migrate --check
bash "${management}" check_runtime_health
if ${enable_health} && ! ${enable_backups}; then
    bash "${management}" check_runtime_health --require-backup
fi

staging=$(mktemp -d /run/studycrew-install.XXXXXX)
trap 'rm -rf -- "${staging}"' EXIT
python3 - "${app}" "${host}" "${staging}" <<'PY'
from pathlib import Path
import sys

app, host, staging = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
site = (app / "deploy/nginx/studycrew.conf").read_text()
assert site.count("    server_tokens off;") == 3, "Review the changed Nginx template first."
site = site.replace("__DOMAIN__", host)
# A server-level log replaces inherited global logs, including the Ubuntu raw log.
site = site.replace("    server_tokens off;", "    server_tokens off;\n    access_log /var/log/nginx/studycrew-access.log studycrew_privacy;")
before_tls, tls = site.split("    listen 443 ssl;", 1)
assert tls.count("    location / {") == 1, "Review the changed HTTPS location layout first."
tls = tls.replace("    location / {", "    include /etc/nginx/snippets/studycrew-token-routes.conf;\n\n    location / {", 1)
(staging / "studycrew.conf").write_text(before_tls + "    listen 443 ssl;" + tls)
PY

# Back up only the three Nginx files this installer owns. Failed validation
# restores their exact previous state before any service is enabled or reloaded.
nginx_targets=(
    /etc/nginx/conf.d/00-studycrew-privacy.conf
    /etc/nginx/snippets/studycrew-token-routes.conf
    /etc/nginx/sites-available/studycrew
)
for index in "${!nginx_targets[@]}"; do
    target=${nginx_targets[index]}
    [[ ! -L ${target} ]] || fail "Refusing to replace a symlink: ${target}"
    if [[ -e ${target} ]]; then cp -p -- "${target}" "${staging}/previous-${index}"; fi
done
site_link=/etc/nginx/sites-enabled/studycrew
created_link=false
if [[ -e ${site_link} || -L ${site_link} ]]; then
    [[ -L ${site_link} && $(readlink "${site_link}") == /etc/nginx/sites-available/studycrew ]] || fail "Existing StudyCrew enabled site does not match the reviewed layout."
else
    created_link=true
fi
install -d -m 0755 /etc/nginx/snippets /etc/nginx/conf.d /etc/nginx/sites-available /etc/nginx/sites-enabled
install -m 0644 "${app}/deployment/nginx/privacy-logging.conf" "${nginx_targets[0]}"
install -m 0644 "${app}/deployment/nginx/studycrew-token-routes.conf" "${nginx_targets[1]}"
install -m 0644 "${staging}/studycrew.conf" "${nginx_targets[2]}"
if ${created_link}; then ln -s /etc/nginx/sites-available/studycrew "${site_link}"; fi
if ! nginx -t; then
    for index in "${!nginx_targets[@]}"; do
        target=${nginx_targets[index]}
        if [[ -e ${staging}/previous-${index} ]]; then
            cp -p -- "${staging}/previous-${index}" "${target}"
        else
            rm -f -- "${target}"
        fi
    done
    if ${created_link}; then rm -f -- "${site_link}"; fi
    fail "Nginx validation failed; the previous Nginx configuration was restored. No services were enabled."
fi

install -m 0644 "${app}/deploy/systemd/studycrew.service" /etc/systemd/system/studycrew.service
install -m 0644 "${app}/deployment/systemd/studycrew-worker.service" /etc/systemd/system/studycrew-worker.service
install -d -m 0755 /etc/systemd/system/studycrew.service.d
cat > /etc/systemd/system/studycrew.service.d/advance-privacy.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/srv/studycrew/venv/bin/uwsgi --ini /srv/studycrew/app/deploy/uwsgi.ini --ini /srv/studycrew/app/deployment/uwsgi-privacy.ini
UNIT
if ${enable_backups} || ${enable_health}; then
    install -d -o studycrew -g www-data -m 0700 "${app}/var/backups"
fi
if ${enable_backups}; then
    for unit in studycrew-backup.service studycrew-backup.timer; do
        install -m 0644 "${app}/deployment/systemd/${unit}" "/etc/systemd/system/${unit}"
    done
fi
if ${enable_health}; then
    for unit in studycrew-health.service studycrew-health.timer; do
        install -m 0644 "${app}/deployment/systemd/${unit}" "/etc/systemd/system/${unit}"
    done
fi
systemctl daemon-reload
systemctl enable postgresql nginx studycrew studycrew-worker
systemctl start postgresql
systemctl restart studycrew studycrew-worker
systemctl reload-or-restart nginx
if ${enable_backups}; then
    systemctl start studycrew-backup.service
    systemctl enable --now studycrew-backup.timer
fi
if ${enable_health}; then
    bash "${management}" check_runtime_health --require-worker --require-backup
    systemctl enable --now studycrew-health.timer
fi
systemctl is-active postgresql nginx studycrew studycrew-worker
echo "Services installed. Verify /health/, real SMTP delivery, authorised journeys and reboot recovery before acceptance."
