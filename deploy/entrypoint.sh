#!/bin/sh
# Bring the schema up to date, optionally load the demo content, then start the server.
set -e
flask db upgrade
if [ "${SEED_DEMO:-0}" = "1" ]; then
  flask seed-demo --if-empty
fi
exec "$@"
