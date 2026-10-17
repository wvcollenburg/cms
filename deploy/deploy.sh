#!/usr/bin/env bash
# Deploy to STRATO shared hosting (PLAN §10a). From the repository root, just run:
#   deploy/deploy.sh
# The first time, it asks for the SSH login, the domain, the database and the mailbox, writes
# deploy/deploy.conf (here, not in git) and ~/private/.env (on STRATO), and after the deploy
# makes you the first key holder. Later runs ask nothing.
#
# deploy/deploy.conf holds:
#   STRATO_SSH=user@ssh.strato.de    # or an ssh alias
#   SITE_DOMAIN=example.nl           # the address the site runs on (BASE_URL)
#   DOMAIN_DIR=example.nl            # the folder in the STRATO home that address points at
#   CGI_DIR=cgi-bin                  # optional: folder for the CGI script, if cgi-bin is taken
#
# What a deploy does:
#   1. builds locally: the code, compiled translations, and every dependency as a wheel for
#      the server's processor, glibc and Python (read over ssh; no compiler there), in lib/
#   2. uploads one tarball over ssh (no rsync needed on either side)
#   3. runs `flask db upgrade` with the NEW code; if that fails, the live site is untouched
#   4. swaps ~/app and <web root>/static in one move each, installs .htaccess and the CGI script
#   5. clears the page cache (templates may have changed)
# The previous version stays in ~/app.previous until the next deploy.
set -euo pipefail
cd "$(dirname "$0")/.."

ask() {  # ask VAR "question" [default]; a trailing "secret" hides the typing
  local var=$1 question=$2 default=${3:-} answer
  if [ "${4:-}" = secret ]; then
    IFS= read -rsp "$question: " answer; echo  # IFS=: keep spaces at either end of a password
  else
    IFS= read -rp "$question${default:+ [$default]}: " answer
  fi
  answer=${answer:-$default}
  [ -n "$answer" ] || { echo "An answer is needed." >&2; exit 1; }
  printf -v "$var" '%s' "$answer"
}

if [ ! -f deploy/deploy.conf ]; then
  echo "First deploy: a few questions (the answers are kept in deploy/deploy.conf)."
  ask SITE_DOMAIN "Address the website runs on (where a redirect ends up), e.g. createur.nl"
  ask DOMAIN_DIR "Folder in your STRATO home that this address points at" "$SITE_DOMAIN"
  ask STRATO_SSH "SSH login from the STRATO panel, as user@host (e.g. user@ssh.strato.de)"
  printf 'STRATO_SSH=%s\nSITE_DOMAIN=%s\nDOMAIN_DIR=%s\n' "$STRATO_SSH" "$SITE_DOMAIN" "$DOMAIN_DIR" > deploy/deploy.conf
fi
. deploy/deploy.conf
: "${STRATO_SSH:?set STRATO_SSH in deploy/deploy.conf}"
: "${DOMAIN_DIR:?set DOMAIN_DIR in deploy/deploy.conf}"
SITE_DOMAIN=${SITE_DOMAIN:-$DOMAIN_DIR}
CGI_DIR=${CGI_DIR:-cgi-bin}
UV=${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}
# One SSH connection for the whole run, so the password is asked once. Tests swap in a stand-in.
SSH=${SSH:-ssh -o ControlMaster=auto -o ControlPath=$HOME/.ssh/cm-createur-%C -o ControlPersist=2m}
remote() { $SSH "$STRATO_SSH" "$@" </dev/null; }

if [ -n "$(git status --porcelain)" ]; then
  echo "Note: you have uncommitted changes; they are deployed as they are on disk." >&2
fi

echo "==> Checking the server (STRATO may ask for your SSH password)"
# STRATO runs both x86_64 (glibc 2.17) and arm64 (Debian 12, glibc 2.36) hosting, so the
# libraries are built for whatever this server turns out to be.
read -r REMOTE_HOME PYTHON PY_VERSION WHEEL_PLATFORM < <(remote 'P=$(command -v python3) && echo "$HOME $P $($P -c "
import platform, sys
glibc = platform.libc_ver()[1].split(\".\")
print(\"%d.%d\" % sys.version_info[:2], \"%s-manylinux_%s_%s\" % (platform.machine(), glibc[0], glibc[1]))
")"')
APP_DIR="$REMOTE_HOME/app"
PRIVATE_DIR="$REMOTE_HOME/private"
WEBROOT="$REMOTE_HOME/$DOMAIN_DIR"
echo "    home $REMOTE_HOME, $PYTHON ($PY_VERSION, $WHEEL_PLATFORM), web root $WEBROOT"
remote "test ! -e '$APP_DIR' || test -f '$APP_DIR/flask'" || {
  echo "$APP_DIR exists but wasn't made by this script. Move it away first." >&2; exit 1; }
if ! remote "test -d '$WEBROOT'"; then
  remote "mkdir -p '$WEBROOT'"
  echo "    made the folder $WEBROOT: in the STRATO panel, point $SITE_DOMAIN at the folder $DOMAIN_DIR"
fi

FIRST_RUN=0
if ! remote "test -f '$PRIVATE_DIR/.env'"; then
  FIRST_RUN=1
  echo "No settings on the server yet. From the STRATO panel:"
  ask DB_HOST "  Database host (Datenbankserver)"
  ask DB_NAME "  Database name"
  ask DB_USER "  Database user" "$DB_NAME"
  ask DB_PASSWORD "  Database password" "" secret
  ask MAIL_USER "  Mailbox that sends the login links (its login, not an alias)"
  ask MAIL_PASSWORD "  Password of that mailbox" "" secret
  ask MAIL_FROM_ADDR "  Sender address people see (may be an alias of that mailbox)" "$MAIL_USER"
  DOMAIN=$SITE_DOMAIN DOMAIN_DIR=$DOMAIN_DIR DB_HOST=$DB_HOST DB_NAME=$DB_NAME DB_USER=$DB_USER \
    DB_PASSWORD=$DB_PASSWORD MAIL_USER=$MAIL_USER MAIL_PASSWORD=$MAIL_PASSWORD MAIL_FROM_ADDR=$MAIL_FROM_ADDR \
    python3 deploy/strato/make_env.py | $SSH "$STRATO_SSH" \
    "umask 077 && mkdir -p '$PRIVATE_DIR' && cat > '$PRIVATE_DIR/.env'"
  echo "    settings written to $PRIVATE_DIR/.env (with fresh secret keys)"
fi

echo "==> Building"
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$BUILD/app" "$BUILD/web/cgi-bin"
tar -c --exclude=__pycache__ --exclude='*.pyc' --exclude='*.mo' app migrations | tar -x -C "$BUILD/app"
"$UV" run --frozen pybabel -q compile -d "$BUILD/app/app/translations"
"$UV" export --frozen --no-dev --no-emit-project --no-hashes --quiet -o "$BUILD/requirements.txt"
"$UV" pip install --quiet --target "$BUILD/app/lib" --python-version "$PY_VERSION" \
  --python-platform "$WHEEL_PLATFORM" --only-binary :all: -r "$BUILD/requirements.txt"
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
if ! remote "cd ~/.deploy-new/app && PYTHONPATH=.:lib CREATEUR_ENV_FILE='$PRIVATE_DIR/.env' \
  INSTANCE_PATH='$PRIVATE_DIR/instance' '$PYTHON' -m flask --app app db upgrade" 2>&1 | tee "$BUILD/migrate.log"; then
  # Only a refused or unreachable database means the answers were wrong; anything else is ours.
  if [ "$FIRST_RUN" = 1 ] && grep -qE "OperationalError: \((1044|1045|1049|2003|2005)" "$BUILD/migrate.log"; then
    remote "rm -f '$PRIVATE_DIR/.env'"
    echo "The database didn't accept the settings (see the error above). Check the database" >&2
    echo "details in the STRATO panel and run deploy/deploy.sh again; it will ask once more." >&2
  else
    echo "Stopped before switching: the live site is unchanged and the settings are kept." >&2
  fi
  exit 1
fi

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
  # STRATO's "coming soon" placeholder would shadow the site; keep it, but out of the way.
  if [ -e '$WEBROOT/'\$f ]; then mv '$WEBROOT/'\$f '$WEBROOT/'\$f.strato-placeholder; echo "    moved STRATO's \$f aside"; fi
done
EOF

if [ "$FIRST_RUN" = 1 ]; then
  echo "==> Making you the first key holder"
  ask ADMIN_EMAIL "Your e-mail address"
  ask ADMIN_NAME "Your name"
  remote "'$APP_DIR/flask' create-superadmin '${ADMIN_EMAIL//\'/}' '${ADMIN_NAME//\'/}'"
fi

echo "==> Done: https://$SITE_DOMAIN/  (log in at https://$SITE_DOMAIN/auth/login)"
