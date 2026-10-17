#!@PYTHON@
# CGI entry point on STRATO shared hosting (PLAN §10a). Apache starts this for every request
# that .htaccess doesn't answer from a file (static, media, cached page).
# deploy.sh fills in the @...@ values; don't edit the copy on the server.
import os
import sys
from urllib.parse import unquote_to_bytes

APP_DIR = "@APP_DIR@"
PRIVATE_DIR = "@PRIVATE_DIR@"

sys.path[0:0] = [APP_DIR, os.path.join(APP_DIR, "lib")]
os.environ.setdefault("CREATEUR_ENV_FILE", os.path.join(PRIVATE_DIR, ".env"))
os.environ.setdefault("INSTANCE_PATH", os.path.join(PRIVATE_DIR, "instance"))
LOG_DIR = os.path.join(PRIVATE_DIR, "logs")


def _fail(exc_text: str) -> None:
    """The app couldn't even start: log why, and give the visitor a plain 500."""
    import time
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "cgi-error.log"), "a") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{exc_text}\n")
    except OSError:
        pass
    sys.stdout.write("Status: 500 Internal Server Error\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
                     "De website heeft even een storing. Probeer het later opnieuw.\n")


def main() -> None:
    import logging
    from wsgiref.handlers import CGIHandler

    from app import create_app

    flask_app = create_app()
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = logging.FileHandler(os.path.join(LOG_DIR, "app.log"))
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    flask_app.logger.addHandler(handler)

    def wsgi(environ, start_response):
        # .htaccess rewrites every URL to this script. Without this, Flask would see the script as
        # the mount point and build links like /cgi-bin/createur.cgi/makers.
        path = environ.get("REQUEST_URI", "/").split("?", 1)[0] or "/"
        environ["SCRIPT_NAME"] = ""
        environ["PATH_INFO"] = unquote_to_bytes(path).decode("latin-1")
        return flask_app(environ, start_response)

    CGIHandler().run(wsgi)


try:
    main()
except Exception:
    import traceback
    _fail(traceback.format_exc())
