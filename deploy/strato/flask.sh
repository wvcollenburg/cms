#!/bin/sh
# The `flask` command on STRATO, with the same code, libraries and settings as the website.
# deploy.sh installs this as ~/app/flask. Over SSH, for example:
#   ~/app/flask db upgrade
#   ~/app/flask create-superadmin you@example.org "Your Name"
#   ~/app/flask page-cache warm
APP_DIR="@APP_DIR@"
PRIVATE_DIR="@PRIVATE_DIR@"
export PYTHONPATH="$APP_DIR:$APP_DIR/lib"
export CREATEUR_ENV_FILE="${CREATEUR_ENV_FILE:-$PRIVATE_DIR/.env}"
export INSTANCE_PATH="${INSTANCE_PATH:-$PRIVATE_DIR/instance}"
cd "$APP_DIR" || exit 1
exec "@PYTHON@" -m flask --app app "$@"
