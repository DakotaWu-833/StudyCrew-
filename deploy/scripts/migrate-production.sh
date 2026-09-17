#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

# Do not pass unrelated values from the administrator's shell to the app user.
if [[ ${STUDYCREW_CLEAN_ENV:-0} != 1 ]]; then
    exec env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin STUDYCREW_CLEAN_ENV=1 \
        /bin/bash "$0" "$@"
fi

environment_file=/etc/studycrew/studycrew.env
application_root=/srv/studycrew/app
python_binary=/srv/studycrew/venv/bin/python

if [[ ! -r ${environment_file} ]]; then
    echo "Missing ${environment_file}." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "${environment_file}"
set +a

read -rsp "Migration-role database password: " migration_password
echo
export DB_USER=studycrew_migrator
export DB_PASSWORD="${migration_password}"
unset migration_password
trap 'unset DB_PASSWORD' EXIT

runuser -u studycrew --preserve-environment -- \
    "${python_binary}" "${application_root}/manage.py" migrate --noinput
runuser -u studycrew --preserve-environment -- \
    "${python_binary}" "${application_root}/manage.py" collectstatic --noinput

echo "Migrations and static collection completed."
