#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this script with sudo." >&2
    exit 1
fi
if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <management-command> [non-secret arguments...]" >&2
    exit 2
fi

# Import the protected production environment without retaining unrelated
# administrator-shell variables. Never pass a password as a command argument.
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
# The deployed environment template is deliberately valid shell syntax.
# shellcheck disable=SC1090
source "${environment_file}"
set +a

exec runuser -u studycrew --preserve-environment -- \
    "${python_binary}" "${application_root}/manage.py" "$@"
