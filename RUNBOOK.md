# Runbook: the Createur website on STRATO

For whoever looks after the website: William now, Arwin (or the next key holder) later.
Background and reasons are in [PLAN.md](PLAN.md) §10a; this file is the how-to.

## What runs where

| What | Where |
|---|---|
| Website, database, mailbox for the login links | The collective's STRATO account (Hosting Basic) |
| Daily task caller (cron, `deploy/call-tasks.sh`) | William's server |
| "Did the daily tasks run?" alarm | Healthchecks.io (the collective's account) |
| Nightly backup pull | William's server |

On STRATO, in the SSH home folder:

```
~/app/                     code + libraries (lib/), not reachable from the web
~/app/flask                the `flask` command for this site (see "Everyday")
~/app.previous/            the version before the last deploy
~/private/.env             settings and passwords (chmod 600)
~/private/logs/            app.log (errors), cgi-error.log (the app couldn't start)
~/private/hidden-media/    photos of hidden maker pages
~/<domain>/                web root: .htaccess, cgi-bin/createur.cgi, static/, media/, _cache/
```

Apache serves photos, CSS and cached pages straight from disk. Everything else (admin, login,
the first visit to a page after a change) starts `createur.cgi`, which runs the Flask app once
for that request.

## First-time setup

1. **SSH.** In the STRATO panel, switch on SSH and note the user and host. On your own machine,
   in `~/.ssh/config`, add the following so a deploy asks for the password once, not six times:
   ```
   Host strato
     HostName ssh.strato.de
     User <strato ssh user>
     ControlMaster auto
     ControlPath ~/.ssh/cm-%r@%h-%p
     ControlPersist 10m
   ```
   Add your public key to `~/.ssh/authorized_keys` on STRATO if the package allows it.
2. **Database.** STRATO panel → Databases → new MariaDB database. Note the host, database name,
   user and password.
3. **Mailbox and DNS.** Create `noreply@<domain>` (or similar) and set SPF, DKIM and DMARC for the
   domain. DNS takes hours, so do this first.
4. **SSL.** Switch on the certificate for the domain, and point the domain at the folder `<domain>`
   in the home folder.
5. **Settings.** On STRATO: `mkdir -p ~/private`, then create `~/private/.env` from
   [deploy/strato/env.example](deploy/strato/env.example) and fill it in. Make a fresh `SECRET_KEY`
   and `TASK_SECRET` with `python3 -c "import secrets; print(secrets.token_hex(32))"`.
6. **Deploy settings.** On your own machine, create `deploy/deploy.conf` (not in git):
   ```
   STRATO_SSH=strato
   DOMAIN_DIR=<domain>
   ```
7. **Deploy:** `deploy/deploy.sh`. The first run creates the tables.
8. **First key holder.** Over SSH: `~/app/flask create-superadmin you@example.org "Your Name"`,
   then log in at `https://<domain>/auth/login`. Invite everyone else from the admin.
9. **Daily tasks.** On William's server, add `/etc/cron.d/createur-tasks`:
   ```
   15 3 * * * createur CREATEUR_TASK_SECRET=<TASK_SECRET from .env> /opt/createur/call-tasks.sh https://<domain>
   ```
   Then create a check on Healthchecks.io (period 1 day, grace 1 day), put its ping URL in
   `HEALTHCHECK_URL` in `~/private/.env`, and add the superadmins as alert recipients.
10. **Backups.** See "Backups" below.
11. Remove STRATO's placeholder `index.html` from the web root, if there is one (deploy.sh warns).

## Spike: check these on the real package (PLAN §10a)

| # | How to check | Pass when |
|---|---|---|
| S3 | `curl -s -o /dev/null -w '%{time_total}\n' https://<domain>/auth/login` a few times | Under 1.5 s |
| S4 | Ask STRATO, or look for `mod_fcgid` in their docs | Nice to have |
| S5 | Open `/`, `/makers` and a maker page twice. The second time, `curl -sI` shows `Cache-Control: no-cache` and *no* `X-Page-Cache` header (Apache served the file) | Pages load; `/_cache/` and `/cgi-bin/createur.cgi` give 404 |
| S6 | Upload a 5 MB photo as a maker | The photo shows up |
| S8 | Log in with a Gmail and an Outlook address | The link arrives in the inbox, not spam |
| S9 | `~/app/flask db upgrade` ran during deploy without errors | Done |

**If the CGI script doesn't run** (you see its source code, a 403, or "script not found"):
- STRATO may reserve the name `cgi-bin`. Put `CGI_DIR=app-cgi` in `deploy/deploy.conf` and deploy again.
- Check `~/private/logs/cgi-error.log`.
- Check that `head -1 ~/<domain>/cgi-bin/createur.cgi` names a Python that exists (`python3 --version`).

**If it all fails:** point the domain's DNS at the container (Profile A); the code is the same.

## Everyday

- **Deploy a new version:** commit, then run `deploy/deploy.sh` from the repository root. It
  migrates the database with the new code *before* switching, so a failed migration leaves the
  live site as it was.
- **Undo the last deploy** (code only; database changes stay):
  `ssh strato 'mv ~/app ~/app.broken && mv ~/app.previous ~/app && ~/app/flask page-cache clear'`.
  Then `git checkout` the previous commit and run `deploy/deploy.sh` again, which also restores
  `static/`.
- **Commands on the server:** `~/app/flask <command>`, for example `page-cache warm`,
  `run-tasks`, `create-superadmin`.
- **Errors:** `tail -50 ~/private/logs/app.log`. If the site shows "De website heeft even een
  storing", the app couldn't start: see `~/private/logs/cgi-error.log`.
- **Change a setting:** edit `~/private/.env`, then `~/app/flask page-cache clear`. There's no
  server to restart; every request reads the settings again.

## Backups

STRATO keeps its own backups. On top of that, every night William's server pulls a copy:

```bash
#!/usr/bin/env bash
# /opt/createur/backup.sh: run nightly from cron on William's server
set -euo pipefail
D=/srv/backup/createur
mkdir -p "$D"
ssh strato 'PYTHONPATH=~/app/lib python3 -' > "$D/db.sql" <<'PY'
import os, urllib.parse as u
from dotenv import dotenv_values
p = u.urlparse(dotenv_values(os.path.expanduser("~/private/.env"))["DATABASE_URL"])
os.environ["MYSQL_PWD"] = u.unquote(p.password)
os.execvp("mysqldump", ["mysqldump", "--single-transaction", "-h", p.hostname, "-u", u.unquote(p.username),
          p.path.lstrip("/")])
PY
rsync -a --delete strato:'<domain>/media/' "$D/media/"
rsync -a --delete strato:private/hidden-media/ "$D/hidden-media/"
restic backup "$D"   # off-site, 30 days retention
```

Check once that `mysqldump` and `rsync` exist on STRATO. A restore is the reverse: load `db.sql`
into the database, copy `media/` back, then `~/app/flask page-cache clear`.

## Task caller

The daily tasks (rebuilding the page cache; later the purge of removed makers) are started by
`deploy/call-tasks.sh` on William's server, signed with `TASK_SECRET`. If that server stops,
the site still runs them during normal visits (the fallback), and Healthchecks.io sends an
e-mail when a day passes without a run.

**Handing over:** move the cron job to someone else's server or to cron-job.org, make a new
`TASK_SECRET`, put it in `~/private/.env` and give it to the new caller.

## Access check for a new key holder

Can they log in to the website as superadmin, to the STRATO panel and to Healthchecks.io, and
do they know where this file is?
