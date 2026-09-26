#!/bin/sh
# Bring the schema up to date, optionally load the demo content, then start the server.
set -e
if [ "${DEV_RELOAD:-0}" = "1" ]; then
  # The code is mounted from the host (compose.dev.yaml): compile the translations outside it,
  # so the container never writes into your checkout.
  rm -rf /tmp/translations
  cp -r app/translations /tmp/translations
  pybabel -q compile -d /tmp/translations
  export BABEL_TRANSLATION_DIRECTORIES=/tmp/translations
fi
flask db upgrade
# New code may bring new templates: never serve pages rendered by the previous version.
flask page-cache clear
if [ "${SEED_DEMO:-0}" = "1" ]; then
  flask seed-demo --if-empty
fi
exec "$@"
