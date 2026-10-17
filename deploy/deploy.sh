#!/usr/bin/env bash
# Deploy to STRATO shared hosting (PLAN §10a). Run from the repository root:
#   deploy/deploy.sh                 # uses deploy/deploy.conf
# deploy/deploy.conf (not in git) holds:
#   STRATO_SSH=strato                # an ssh alias or user@host (key login, see RUNBOOK.md)
#   DOMAIN_DIR=example.nl            # the web root folder in the STRATO home
#   CGI_DIR=cgi-bin                  # optional: folder for the CGI script, if cgi-bin is taken
#
# What it does:
#   1. builds locally: the code, compiled translations, and every dependency as a wheel for
#      STRATO's Python on glibc 2.17 (no compiler there), in lib/
#   2. uploads one tarball over ssh (no rsync needed on either side)
#   3. runs `flask db upgrade` with the NEW code; if that fails, the live site is untouched
#   4. swaps ~/app and <web root>/static in one move each, installs .htaccess and the CGI script
#   5. clears the page cache (templates may have changed)
# The previous version stays in ~/app.previous until the next deploy.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f deploy/deploy.conf ] && . deploy/deploy.conf
: "${STRATO_SSH:?set STRATO_SSH in deploy/deploy.conf}"
: "${DOMAIN_DIR:?set DOMAIN_DIR in deploy/deploy.conf}"
CGI_DIR=${CGI_DIR:-cgi-bin}
UV=${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}
SSH=${SSH:-ssh}  # tests swap this for a stand-in server

if [ -n "$(git status --porcelain)" ]; then
  echo "Note: you have uncommitted changes; they are deployed as they are on disk." >&2
fi

echo "==> Checking the server"
read -r REMOTE_HOME PYTHON PY_VERSION < <($SSH "$STRATO_SSH" \
  'P=$(command -v python3) && echo "$HOME $P $($P -c "import sys; print(\"%d.%d\" % sys.version_info[:2])")"')
APP_DIR="$REMOTE_HOME/app"
PRIVATE_DIR="$REMOTE_HOME/private"
WEBROOT="$REMOTE_HOME/$DOMAIN_DIR"
echo "    home $REMOTE_HOME, $PYTHON ($PY_VERSION), web root $WEBROOT"
$SSH "$STRATO_SSH" "test -f '$PRIVATE_DIR/.env'" || {
  echo "Missing $PRIVATE_DIR/.env on the server. Create it from deploy/strato/env.example first." >&2; exit 1; }
$SSH "$STRATO_SSH" "test ! -e '$APP_DIR' || test -f '$APP_DIR/flask'" || {
  echo "$APP_DIR exists but wasn't made by this script. Move it away first." >&2; exit 1; }
$SSH "$STRATO_SSH" "test -d '$WEBROOT'" || {
  echo "No web root at $WEBROOT. Check DOMAIN_DIR, or create the folder and point the domain at it." >&2; exit 1; }

echo "==> Building"
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$BUILD/app" "$BUILD/web/cgi-bin"
tar -c --exclude=__pycache__ --exclude='*.pyc' --exclude='*.mo' app migrations | tar -x -C "$BUILD/app"
"$UV" run --frozen pybabel -q compile -d "$BUILD/app/app/translations"
"$UV" export --frozen --no-dev --no-emit-project --no-hashes --quiet -o "$BUILD/requirements.txt"
"$UV" pip install --quiet --target "$BUILD/app/lib" --python-version "$PY_VERSION" \
  --python-platform x86_64-manylinux_2_17 --only-binary :all: -r "$BUILD/requirements.txt"
mv "$BUILD/app/app/static" "$BUILD/web/static"  # Apache serves these; the app only builds the URLs
mkdir "$BUILD/app/app/static"

fill() {
  sed -e "s|@PYTHON@|$PYTHON|g" -e "s|@APP_DIR@|$APP_DIR|g" \
      -e "s|@PRIVATE_DIR@|$PRIVATE_DIR|g" -e "s|@WEBROOT@|$WEBROOT|g" -e "s|@CGI_DIR@|$CGI_DIR|g" "$1" > "$2"
}
fill deploy/strato/flask.sh "$BUILD/app/flask"
fill deploy/strato/createur.cgi "$BUILD/web/cgi-bin/createur.cgi"
fill deploy/strato/htaccess "$BUILD/web/.htaccess"
chmod 755 "$BUILD/app/flask" "$BUILD/web/cgi-bin" "$BUILD/web/cgi-bin/createur.cgi"
echo "    $(du -sh "$BUILD/app/lib" | cut -f1) of libraries"

echo "==> Uploading"
tar -C "$BUILD" -czf - app web | $SSH "$STRATO_SSH" \
  'rm -rf ~/.deploy-new && mkdir ~/.deploy-new && tar -xzf - -C ~/.deploy-new'

echo "==> Migrating the database (new code, old site still live)"
$SSH "$STRATO_SSH" "cd ~/.deploy-new/app && PYTHONPATH=.:lib CREATEUR_ENV_FILE='$PRIVATE_DIR/.env' \
  INSTANCE_PATH='$PRIVATE_DIR/instance' '$PYTHON' -m flask --app app db upgrade"

echo "==> Switching to the new version"
$SSH "$STRATO_SSH" bash -s <<EOF
set -euo pipefail
umask 022
mkdir -p '$PRIVATE_DIR/instance' '$PRIVATE_DIR/logs' '$WEBROOT/media' '$WEBROOT/_cache' '$WEBROOT/$CGI_DIR'
chmod 700 '$PRIVATE_DIR'
chmod 600 '$PRIVATE_DIR/.env'
N=~/.deploy-new
rm -rf ~/app.previous '$WEBROOT/static.previous'
if [ -d '$APP_DIR' ]; then mv '$APP_DIR' ~/app.previous; fi
mv \$N/app '$APP_DIR'
if [ -d '$WEBROOT/static' ]; then mv '$WEBROOT/static' '$WEBROOT/static.previous'; fi
mv \$N/web/static '$WEBROOT/static'
cp \$N/web/cgi-bin/createur.cgi '$WEBROOT/$CGI_DIR/createur.cgi'
chmod 755 '$WEBROOT/$CGI_DIR' '$WEBROOT/$CGI_DIR/createur.cgi'
cp \$N/web/.htaccess '$WEBROOT/.htaccess'
rm -rf \$N '$WEBROOT/static.previous'
'$APP_DIR/flask' page-cache clear
for f in index.html index.htm index.php; do
  if [ -e '$WEBROOT/'\$f ]; then echo "WARNING: $WEBROOT/\$f (STRATO's placeholder?) may shadow the site; remove it." >&2; fi
done
EOF

echo "==> Done. Check https://$DOMAIN_DIR/ and, after the first deploy, see RUNBOOK.md."
