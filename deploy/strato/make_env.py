"""Write the production .env for STRATO from the answers deploy.sh collected (passed as
environment variables). Prints the file to stdout; deploy.sh sends it straight to the server.

Quoting matters: the database password goes into a URL (percent-encoded), and every value is
single-quoted so characters like # or spaces in a password survive python-dotenv."""
import os
import secrets
from urllib.parse import quote

a = os.environ


def q(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


domain = a["DOMAIN"]
db_url = (f"mysql+pymysql://{quote(a['DB_USER'], safe='')}:{quote(a['DB_PASSWORD'], safe='')}"
          f"@{a['DB_HOST']}/{quote(a['DB_NAME'], safe='')}?charset=utf8mb4")
settings = {
    "SECRET_KEY": secrets.token_hex(32),
    "BASE_URL": f"https://{domain}",
    "DATABASE_URL": db_url,
    "MEDIA_ROOT": f"~/{a['DOMAIN_DIR']}/media",
    "PAGE_CACHE_ROOT": f"~/{a['DOMAIN_DIR']}/_cache",
    "PRIVATE_ROOT": "~/private",
    "MAIL_SERVER": "smtp.strato.de",
    "MAIL_PORT": "587",
    "MAIL_USE_TLS": "1",
    "MAIL_USERNAME": a["MAIL_USER"],
    "MAIL_PASSWORD": a["MAIL_PASSWORD"],
    "MAIL_FROM": f"Broedplaats de Createur <{a.get('MAIL_FROM_ADDR') or a['MAIL_USER']}>",
    "DEMO_MODE": "0",
    "DEMO_NIGHTLY_RESET": "0",
    "TASK_SECRET": secrets.token_hex(32),
    "HEALTHCHECK_URL": "",
}
print("# Made by deploy/deploy.sh on the first deploy. Edit freely; see deploy/strato/env.example.")
for key, value in settings.items():
    print(f"{key}={q(value)}")
