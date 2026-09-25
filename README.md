# Broedplaats de Createur: CMS

Flask + MariaDB CMS for the collective's website. The plan and all decisions are in [PLAN.md](PLAN.md).

## PoC with Docker Compose

App (Gunicorn) + MariaDB + Mailpit, with the demo content loaded on first start:

```bash
docker compose up --build -d
```

- Site: http://localhost:8080 (demo logins at `/auth/demo`)
- Mail inbox: http://localhost:8025 (magic links land here)
- Reset the demo: `docker compose exec app flask seed-demo --reset`
- Start from scratch, including the database: `docker compose down -v`

Settings you may want to override in the shell or in `.env`: `APP_PORT`, `MAILPIT_PORT`,
`POC_BASE_URL` (the public URL, e.g. `https://createur.<demolabs-domain>`), `DEMO_HOSTS` (must
include that hostname, or the app refuses to start), `PROXY_HOPS=1` behind a reverse proxy,
`SECRET_KEY`, `DB_PASSWORD`.

### While developing: no rebuild per update

`compose.dev.yaml` mounts `app/` and `migrations/` from the checkout (read-only) and runs Gunicorn
with `--reload`:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build   # first time
git pull                                                          # code/templates/CSS: live
docker compose restart app                                        # after .po or migration changes
docker compose up -d --build                                      # only when dependencies change
```

Tip: put `COMPOSE_FILE=compose.yaml:compose.dev.yaml` in `.env`, then plain `docker compose` uses both.

## Local development without Docker

Tonight's setup runs on SQLite; the STRATO-like VM with MariaDB comes next (PLAN §10b).

```bash
# once
curl -LsSf https://astral.sh/uv/install.sh | sh     # installs uv in ~/.local/bin
uv sync --python 3.12
cp .env.example .env
uv run pybabel compile -d app/translations          # .mo files are not committed
FLASK_APP=app uv run flask seed-demo --reset        # demo content + generated photos

# every time
./tools/mailpit --listen 127.0.0.1:8025 --smtp 127.0.0.1:1025 &   # mail inbox: http://localhost:8025
FLASK_APP=app uv run flask run                                     # site: http://localhost:5000
```

Mailpit is a single binary: download `mailpit-darwin-arm64.tar.gz` from
github.com/axllent/mailpit/releases into `tools/`.

### Demo users (DEMO_MODE=1 only)

`/auth/demo` has one-click logins. All demo users share the password in `DEMO_PASSWORD`
(default `createur-demo`); the magic link works too, and the mail lands in Mailpit.

| Who | E-mail | Can |
|---|---|---|
| Jan | jan@demo.example.org | maker (own page) |
| Sanne, Bo | sanne@ / bo@demo.example.org | makers sharing one page (duo) |
| Noor | noor@demo.example.org | maker + webmaster |
| Sleutelhouder | sleutel@demo.example.org | superadmin |

Seeded states: `/pieter-smid` is hidden (named "no longer active" 404), `/henk-houtwerk` is a
tombstone with a name, `/oud-atelier` one without (deletion request), and `/en/contact` has no
English version, so it shows the Dutch page with a notice.

### Tests

```bash
uv run pytest
```

### Translations

Interface strings are English msgids with a Dutch catalog, which follows the plain-language word list in PLAN §6a.

```bash
uv run pybabel extract -F babel.cfg -k _l -o app/translations/messages.pot .
uv run pybabel update -i app/translations/messages.pot -d app/translations
# edit app/translations/nl/LC_MESSAGES/messages.po, then compile
uv run pybabel compile -d app/translations
```

### Database migrations

`flask seed-demo --reset` uses `create_all` for speed. For MariaDB/STRATO use Alembic:

```bash
DATABASE_URL='mysql+pymysql://user:pw@host/createur?charset=utf8mb4' FLASK_APP=app uv run flask db upgrade
```
