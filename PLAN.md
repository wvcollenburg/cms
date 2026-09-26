# Broedplaats de Createur: CMS plan

Status: v1.3 (26 Sep 2026): maker pages entirely in the maker's language (D27); static page cache built (§8)
Stack: Flask + MariaDB, built in-house; two deployment profiles (VPS/self-host, or STRATO shared hosting)
Owner: William van Collenburg

---

## 0. Decisions log

| # | Topic | Decision |
|---|---|---|
| D1 | Build or buy | Custom build with Flask and a relational DB (MariaDB, see D16) |
| D2 | Login | Invite-only; magic link by default, password optional |
| D3 | Editing rights | Only a space's own members can edit it. Webmasters and superadmins **never** edit maker content |
| D4 | Maker removal | Hide → 404 page saying the space is no longer active → automatic purge after 60 days. A superadmin can purge immediately or postpone up to 1 year after the hide date |
| D5 | Shared (duo) spaces | Removing one member leaves the space live for the remaining member(s). A space is only hidden when its last member is removed |
| D6 | Languages | NL and EN from the start: site interface and front section in both |
| D7 | Maker content language | Each maker writes in **one language of their choice**. No translations required |
| D8 | 404 "no longer active" page | Shown in the visitor's site language (NL/EN) |
| D9 | Domain | Registered and owned by the collective; William gets admin access |
| D10 | Scale | Fewer than 15 makers. Local storage, no Redis, no object storage needed |
| D11 | Maker URL | The maker proposes a slug (first name, full name or brand), and a webmaster approves it |
| D12 | Instagram | Icon links only. No feed or Meta API |
| D13 | Hosting | **Target: STRATO Hosting Basic (Profile B)**, on the collective's account, after the collective approves. Fallback: STRATO VPS (Profile A) if the spike fails |
| D14 | Tombstone after a deletion request | Name is removed, and the slug stays reserved for 1 year. A superadmin can release it early |
| D15 | Deployment profiles | One codebase that runs as **Profile A** (VPS/self-host: compose, Gunicorn, Caddy) or **Profile B** (STRATO shared hosting: Apache + CGI). See §10a |
| D16 | Database | **MariaDB** (MySQL-compatible) for **both** profiles. Using one database engine everywhere means migrations and tests run against a single engine |
| D17 | Scheduled work | All periodic jobs go through one idempotent **task runner** (`flask run-tasks` / `POST /api/tasks/run`). Profile A calls it from cron. Profile B calls it from an external scheduler, with a time-based fallback that runs it during a normal page request (§10a) |
| D18 | Public page performance | Published pages are **rendered to static HTML** and served directly by the web server. Python only runs for admin, login and pages not yet cached |
| D19 | Proof of concept | Built on a **local VM that mimics STRATO Basic** (Apache + CGI + MariaDB, no root, no cron), so it costs nothing. Deployed to STRATO once the collective approves (§10b) |
| D20 | Launch date | The website goes **live on STRATO and is announced at the opening, Sun 18 Oct 2026**. Timeline and go/no-go on 14 Oct in §11 |
| D21 | Daily task caller | A small **task API** (`POST /api/tasks/run`, HMAC-signed). For now it's called by a **cron job on one of William's servers**. The time-based fallback stays enabled as the safety net. If William leaves the collective, the cron job is handed over (see the runbook) |
| D22 | Initial webmasters | **William** (1st webmaster, also superadmin, and a member of the collective) and **Maartje** (2nd webmaster) |
| D23 | Demo | **In person and remote.** Remote access runs through a subdomain of William's demolabs domain (§10b) |
| D24 | Superadmins | **William** and **Arwin**. Arwin's role is continuity: when William leaves, Arwin gives William's roles to a successor. Arwin doesn't need to be a maker or webmaster |
| D25 | William's roles | William has **all three roles**: maker (with his own maker space), webmaster and superadmin. He can edit his own space only as its member. Being webmaster or superadmin gives him no rights over other makers' spaces (D3) |
| D26 | Manuals | A **separate manual for each role**: maker, webmaster, superadmin. They're written for woodworkers, not IT people: plain Dutch, screenshots, one task per page. **Written after go-live.** At launch, William helps makers get their first introduction online in person. The plain-language word list does apply to the website's own text from day one (§6a) |
| D27 | Language of maker pages | A maker page is **entirely in the maker's language**, interface included (menu, footer, buttons). Visitors read the maker's language, so when they get in touch, they do it in a language the maker understands. Only NL and EN are offered: most Dutch visitors understand English. Replaces the earlier "interface follows the visitor" rule (§2). It also means every public page depends only on its URL, which keeps the page cache simple (§8) |

---

## 1. Goals

- One public site with two parts: a **front section** about the collective (`/`) and a **personal space per maker** (`/<maker-slug>`).
- Makers edit **only their own space**, and need no technical knowledge to do it.
- Webmasters edit the **front section** and manage makers.
- Content types: **articles**, **galleries**, **videos** (YouTube/Vimeo) and **social links** (Instagram, YouTube and others, as icon links).
- Bilingual interface (NL/EN), privacy-friendly (AVG/GDPR), cheap to run, and easy to hand over.

### Out of scope (for now)

Webshop and payments, comments, member-only content, newsletters (link out to a newsletter service instead), Instagram feeds.

---

## 2. Site structure and URLs

| URL | Content | Edited by |
|---|---|---|
| `/` · `/en/` | Front page (hero, intro, featured makers, latest news) | Webmaster |
| `/makers` · `/en/makers` | Overview of all active makers | Generated |
| `/nieuws/<slug>` · `/en/news/<slug>` | Collective articles | Webmaster |
| `/agenda` · `/en/agenda` *(phase 2)* | Events | Webmaster |
| `/<page>` · `/en/<page>` | Static front pages (about, contact, privacy) | Webmaster |
| `/<maker>` | Maker home: profile, blocks, socials | That maker |
| `/<maker>/<article-slug>` | Maker article | That maker |
| `/<maker>/galerij/<slug>` | Standalone gallery (optional) | That maker |
| `/beheer/...` | Admin UI | Logged-in users |
| `/auth/...` | Login, magic link | — |

### Languages (D6, D7, D8)

- **Front section:** Dutch lives at the root and English under `/en/`. Each front page and collective article has an NL version, and optionally an EN version. When no EN version exists, the NL content is shown with EN interface text and a small "only available in Dutch" notice. `hreflang` links connect the two versions.
- **Maker pages have no language prefix.** Each maker space has a `lang` (`nl` or `en`) chosen by the maker, and each article can override it. That value sets `<html lang>`, so screen readers and search engines get it right. There's no translation workflow for makers.
- **Interface text** on maker pages (menu, footer, buttons) is in the **maker's language** too (D27), and maker pages have no language toggle.
- The **"no longer active" 404** follows the visitor's language. It's picked from the language-toggle cookie first, then the `Accept-Language` header, then NL. The cookie is functional, so it doesn't need a cookie banner.
- **Admin UI** is also bilingual. Each user chooses their own language in their profile.
- All interface strings go through **Flask-Babel** (`.po` files) from the first commit.

### Slug rules (D11)

- Lowercase letters, digits and hyphens, 3–40 characters, unique.
- **Reserved slugs:** `en, nl, admin, beheer, auth, api, static, media, makers, nieuws, news, agenda, over, about, contact, privacy, sitemap.xml, robots.txt, favicon.ico, ...`
- Front pages, maker spaces and tombstones share one slug namespace, so no two of them can have the same slug.
- **Approval flow:**
  1. The webmaster sets the initial slug when inviting the maker.
  2. The maker can later request a change (`slug_requests`: `pending`, `approved` or `rejected`).
  3. Once a webmaster approves, the old slug goes into `slug_redirects` and returns a 301 redirect.
- Approving a slug doesn't give the webmaster any content rights.

### Routing

The catch-all `/<slug>` is registered **last**. It resolves in this order:

1. A live maker space.
2. A hidden maker space, which gets the "no longer active" 404.
3. A tombstone, which also gets the "no longer active" 404.
4. A front page.
5. A `slug_redirect`.
6. Anything else returns the generic 404.

---

## 3. Roles and RBAC

### Model

A user has **capabilities**, not a single role:

- **Maker**: the user is a member of one or more maker spaces (`space_members`).
- **Webmaster**: a role in `user_roles`.
- A user can be both. A webmaster-only user isn't expected, but the design doesn't block it.
- **Superadmin (D24):** William and **Arwin**. Handles lifecycle and account management. Arwin's key task is **succession**: giving William's roles to someone else when William leaves (see "Succession" below).
- **Initial webmasters (D22):** William and Maartje.

A space can have more than one member, which supports duos (D5). Adding a co-member is done by a webmaster through an invite.

### Permission matrix

**Rule: only a space's own members can edit that space (D3).**

| Action | Maker (own space) | Maker (other space) | Webmaster | Superadmin |
|---|---|---|---|---|
| Edit profile, blocks, articles, media in space | ✅ | ❌ | ❌ | ❌ |
| Publish or unpublish own content, set space language | ✅ | ❌ | ❌ | ❌ |
| Request a slug change | ✅ | ❌ | — | — |
| Approve or reject slug requests | ❌ | ❌ | ✅ | ✅ |
| Edit front pages, news, navigation, site settings (NL + EN) | ❌ | ❌ | ✅ | ✅ |
| Invite users, create spaces, add co-members | ❌ | ❌ | ✅ | ✅ |
| Remove a maker (→ hide, purge scheduled) | ❌ | ❌ | ✅ | ✅ |
| Restore, purge now, postpone purge | ❌ | ❌ | ❌ | ✅ |
| Release a tombstoned slug early | ❌ | ❌ | ❌ | ✅ |
| Grant or revoke the webmaster role | ❌ | ❌ | ❌ | ✅ |
| Grant or revoke the **superadmin** role | ❌ | ❌ | ❌ | ✅ |
| View audit log | own space | ❌ | ✅ | ✅ |

Superadmins have no content-edit rights either. If a superadmin really needs to fix a maker's page, they have to become a member of that space, which is visible and logged.

### Succession (D24)

A superadmin can give or remove the webmaster and superadmin roles, with these safeguards:

- **At least one active superadmin must always remain.** The app refuses to revoke or deactivate the last one. The aim is two at all times.
- **Every role change emails all superadmins**, including the person affected, so nobody's access can be taken over silently.
- **Confirmation and audit:** changing roles means retyping the other person's email address and giving a reason, and the change is written to the audit log.
- **Arwin's flow when William leaves**, one screen under "Beheer → Gebruikers":
  1. Invite the successor, or pick an existing user, and give them **webmaster** and **superadmin**.
  2. Remove William's webmaster and superadmin roles. If William has a maker space, it follows the normal removal flow (§3a), or he keeps it as an ordinary maker.
  3. Hand over the infrastructure using the checklist in `RUNBOOK.md` → "Succession": the STRATO account (already the collective's), the SSH/SFTP password, the task caller and the rotation of its secret, Healthchecks.io alert recipients, and the backup job.
- **Simple for an occasional user:** Arwin will rarely log in. That's why:
  - The magic link is the default login, so there's no password to forget.
  - Accounts are never deactivated for being inactive.
  - The succession steps are a short checklist, not something to remember.
  - Optional 2FA (phase 2) stays optional for him until he's actually needed.

### Enforcement

- All permission checks live in one module (`app/auth/policy.py`).
- Route decorators handle the coarse check, and the policy functions handle the object check.

```python
# policy.py
def can_edit_space(user, space) -> bool:
    # Membership only: no webmaster or superadmin override (D3)
    return space.status in ("draft", "published") and space.id in user.member_space_ids

def can_edit_site(user) -> bool:
    return user.is_superadmin or user.has_role("webmaster")

can_remove_maker = can_edit_site
can_approve_slug = can_edit_site

def can_manage_lifecycle(user) -> bool:   # restore, purge now, postpone, release slug
    return user.is_superadmin

# views
@bp.post("/beheer/space/<int:space_id>/blocks")
@login_required
def add_block(space_id):
    space = db.get_or_404(MakerSpace, space_id)
    if not can_edit_space(current_user, space):
        abort(403)
    ...
```

- Queries are always scoped to the space, e.g. `select(Block).where(Block.owner_id == space.id, ...)`. A bare block ID is never trusted.
- **Every row of the matrix gets a test.**

---

## 3a. Maker removal lifecycle (hide, then purge)

```
 published/draft ──(webmaster/superadmin: remove maker)──▶ hidden ──(purge_at reached)──▶ purged ──▶ tombstone
                                                             │  ▲
                            superadmin: restore ◀────────────┘  │ superadmin: postpone
                                                                 │ (purge_at ≤ hidden_at + 365 d)
                            superadmin: purge now ───────────────┴──▶ purged ──▶ tombstone
```

### Remove maker (webmaster or superadmin)

- A confirmation screen shows the maker, their space(s) and the purge date. The webmaster retypes the slug to confirm, and a reason is required.
- In one transaction:
  - The user is set to `is_active = false`, and their sessions and outstanding magic links are revoked.
  - A space where this user is the **last member** is set to `status = 'hidden'`, `hidden_at = now()`, `purge_at = now() + 60 days`.
  - For a **shared space**, only this user's membership is removed, and the space stays live (D5).
  - An audit entry records who removed the maker, when, and the reason.
- The maker gets an email, in their own UI language, saying the space is offline, with the purge date and a contact address.

### Hidden state

- `/<maker>` and every sub-URL return **HTTP 404** with a dedicated, bilingual template (D8):
  > **NL:** *"De ruimte van **{naam}** bij Broedplaats de Createur is niet meer actief. Wil je in contact komen met {naam}? Neem dan op een andere manier contact met hen op."*
  > **EN:** *"The space of **{name}** at Broedplaats de Createur is no longer active. Want to get in touch with {name}? Please reach out to them another way."*

  The page links to `/makers` and the front page, and is marked `noindex`.
- The space is removed from `/makers`, the front page and the sitemap. Its media URLs return 404.
- The data stays untouched, so a restore loses nothing. The slug stays reserved.

### Superadmin actions

| Action | Effect | Constraint |
|---|---|---|
| **Restore** | Status goes back to `draft`, the user is reactivated, `purge_at` is cleared | Only while hidden |
| **Purge now** | Runs the purge immediately (AVG/GDPR data deletion request) | Reason required; the tombstone has no name |
| **Postpone** | Sets a new `purge_at` (e.g. while a payment issue is sorted out) | `purge_at ≤ hidden_at + 365 days`, enforced in code **and** with a DB `CHECK` |

Each action is audited with the old and new `purge_at` and the reason.

### Purge job

- The purge is one of the tasks in the daily task runner (D17). It selects `status = 'hidden' AND purge_at <= now()`. On Profile B a purge can run up to a day late; this is acceptable for a 60-day window.
- For each space, it:
  1. Deletes media files and all their variants.
  2. Deletes blocks, articles, social links, media rows, memberships, invites, slug requests and the space row.
  3. Deletes the user account if it has no other memberships or roles.
  4. Writes a tombstone and a minimal audit entry ("space X purged"), with no personal content.
- The job is idempotent. If deleting files fails, the space stays hidden and the job retries the next day.
- The superadmin gets an email 7 days before an automatic purge.
- **Backups:** purged data can still exist in restic snapshots until their retention runs out (30 days). The privacy page says so.

### Tombstones (D14)

- `space_tombstones (slug, display_name, purged_at, reason_kind, reserved_until)`.
- **Scheduled purge:** the tombstone keeps the display name, so the named "no longer active" page keeps working. `reserved_until` is set to `purged_at + 1 year`.
- **Deletion request:** `display_name` is NULL, and the page shows a generic "This maker space is no longer active". The slug stays reserved for 1 year.
- **Superadmin override:** a superadmin can release a slug early by deleting the tombstone. This is logged.
- After `reserved_until`, a daily job deletes the tombstone and the slug becomes free.

---

## 4. Content model

### Approach: profile plus ordered blocks

Each maker home and each front page is a **header plus an ordered list of blocks**. Articles are separate items with their own URL.

**Block types (MVP)**

| Block | Content |
|---|---|
| `text` | Rich text (sanitised HTML) |
| `gallery` | Ordered images with captions; grid, masonry or carousel |
| `video` | YouTube/Vimeo URL → provider + ID; click-to-load embed |
| `social` | Icon row: Instagram, YouTube, TikTok, Facebook, website, email (D12) |
| `articles` | Latest N articles from this space |
| `cta` | Button or link (e.g. "Commissions", "Workshop booking") |
| `image` | Single image with caption and optional link |

**Later blocks:** `map`, `contact_form`, `agenda`.

### Tables (simplified)

```
users              id, email (stored lowercased, unique), password_hash (nullable), display_name,
                   ui_lang ('nl' | 'en'), is_active, created_at, last_login_at
user_roles         user_id, role ('webmaster' | 'superadmin')
maker_spaces       id, slug, name, tagline, bio_html, discipline, lang ('nl' | 'en'),
                   accent_color, avatar_media_id, cover_media_id,
                   status ('draft' | 'published' | 'hidden'),
                   hidden_at, purge_at, hidden_by, hide_reason, sort_order, created_at
                   CHECK (purge_at IS NULL OR purge_at <= hidden_at + INTERVAL 365 DAY)
space_members      space_id, user_id, role ('owner' | 'editor')
slug_requests      id, space_id, requested_slug, status, requested_by, decided_by, decided_at
space_tombstones   slug (pk), display_name (nullable), purged_at, reserved_until,
                   reason_kind ('scheduled' | 'deletion_request')
pages              id, slug, status, show_in_nav, nav_order                -- front pages
page_translations  page_id, lang, title, meta_description                  -- nl required
blocks             id, owner_type ('space' | 'page'), owner_id, lang (nullable),
                   type, position, data JSONB, is_visible, updated_at, updated_by
                   -- front pages: one block list per lang; maker spaces: lang NULL
articles           id, owner_type ('space' | 'site'), owner_id, translation_of (nullable),
                   lang, slug, title, excerpt, body_html, cover_media_id,
                   status, published_at, updated_by
media              id, owner_type, owner_id, kind, storage_key, mime, width, height,
                   bytes, alt_text, variants JSONB, uploaded_by
social_links       id, space_id, platform, url, position
site_settings      key, lang (nullable), value JSONB    -- name, address, footer, OG image
slug_redirects     old_slug, target_type, target_id
audit_log          id, user_id, action, object_type, object_id, diff JSONB, at
invites            id, email, space_id (nullable), grants_webmaster, token_hash,
                   expires_at, used_at, invited_by
```

- **Block data** goes in a `JSON` column. In MariaDB this is `LONGTEXT` with a `JSON_VALID` check. Each block type is validated with a Pydantic schema on write. Nothing queries inside the JSON, so MariaDB's lack of a JSONB type doesn't matter.
- **MariaDB conventions** (D16):
  - `utf8mb4` / `utf8mb4_unicode_ci` everywhere, so emoji in bios work.
  - All timestamps stored as UTC `DATETIME`.
  - No partial indexes, and no `RETURNING`.
  - Driver: **PyMySQL**, which is pure Python and installs on shared hosting without compiling.
- Additional tables for Profile B (also used on A):
  - `task_runs (task, last_started_at, last_finished_at, status)` records when each scheduled task last ran.
  - `rate_limits (key, window_start, count)` holds login throttling, because there's no Redis or in-memory store under CGI.
  - ~~`page_cache (path, lang, file, generated_at, depends_on)`~~: not needed. The cache is cleared as a whole on every content change, and the files on disk are the only record (§8).
- **Polymorphic ownership** (`owner_type` + `owner_id`) means one editor and one code path serve both the maker spaces and the front section.
- **Front-page translations:** each language has its own block list (`blocks.lang`). A webmaster can build the EN page by copying the NL blocks and then translating them. Maker spaces don't use `lang` on blocks.

---

## 5. Media handling

- **Client-side resize first:** the browser scales images down to a maximum of 2400 px and converts them to JPEG before uploading (canvas, via a small JS helper). This keeps uploads from phones fast and keeps server work light, which matters under CGI time and memory limits. It also takes care of HEIC from iPhones, because the browser does the conversion.
- Upload types accepted by the server: JPEG, PNG, WebP. Maximum 15 MB per image (the browser's resize is the first line of defence).
- **Pillow** (`pillow-heif` only on Profile A, as an extra) strips EXIF (including GPS), auto-rotates, and creates `400 / 800 / 1600 / 2400 px` WebP variants with a JPEG fallback. These are served via `srcset`.
- With fewer than 15 makers (D10), images are processed **in the request**. A few seconds per upload is fine, and it means no Redis and no worker. If that becomes slow, a DB-backed queue can be added later.
- Storage is a **local volume** behind a small storage interface, so moving to S3-compatible storage later is only a config change.
- Quota: 1 GB per space.
- Alt text is prompted on upload, but not required.
- **Focal point** (26 Sep 2026): each photo has a spot that must stay in view (`media.focus_x/focus_y`, in %, default the middle). Every cropped photo (hero, cover, cards, gallery squares, admin thumbnails) uses it as `object-position`. Next to each photo in the beheeromgeving: *"Kies wat in beeld blijft"*: tap the spot on the full photo, with live previews for a wide screen, a phone and a small box.
- **Video: no self-hosting.** YouTube and Vimeo links only.

---

## 6. Editor UX (makers are not technical)

- Server-rendered admin built with **Jinja + HTMX**, plus SortableJS for drag-to-reorder. No SPA build chain.
- Rich text: **TipTap** or **Trix**, limited to headings, bold/italic, lists, links and quotes. Output is sanitised server-side with **nh3**.
- A **preview** button renders the real public template. Blocks and articles each have a **draft/published** status.
- After login, the dashboard shows "My space" (one entry per membership) and, for webmasters, a "Website" section with NL/EN tabs per page.
- The admin works well on mobile, so makers can upload photos straight from their phone in the workshop.
- Space settings let the maker choose the **content language**, **accent colour** and cover image, and request a slug change.

---

## 6a. Manuals for the three roles (D26)

The users are woodworkers and other makers, not IT people. Anything that seems obvious to William may be gibberish to them. Every role gets its own manual, and the website itself uses the same plain words.

### Principles

- **Organised by task, not by screen.** Each chapter answers one question a user would actually ask: *"How do I put my photos online?"*, not "The gallery block".
- **One task per page:** numbered steps, **a screenshot for every step**, and the button to press circled.
- **Phone first.** Makers will mostly use their phone in the workshop, so the screenshots come from a phone. Desktop is covered where it differs.
- **No jargon.** A banned-words list applies to both the manuals **and** the website's own text:

  | Don't say | Say instead (NL) |
  |---|---|
  | slug, URL | *webadres* (e.g. createur.nl/jan) |
  | CMS, backend, admin | *beheeromgeving* / *je eigen pagina bewerken* |
  | block | *onderdeel* (tekst, fotoalbum, video, knoppen) |
  | publish / draft | *zichtbaar maken* / *nog niet zichtbaar* |
  | magic link | *inloglink per mail* |
  | cache, purge, tombstone | *not mentioned*, or *definitief verwijderen* |
  | role, RBAC | *wat mag jij* |

- **Language:** Dutch first. The maker manual also comes in English, because some makers may write their pages in English (D7).
- **Formats:**
  - A web page inside the site: every screen in the beheeromgeving has a **"Hulp"** link that opens the matching chapter.
  - A PDF of each manual.
  - For makers, a **one-sided A5 quick card** to print and hang in the workshop.
  - Optional: 1–2-minute screen recordings of the most common tasks.
- **Tested before launch.** A manual only counts as finished when someone from its audience has used it to do the tasks **without help**, while William watches silently and notes where they get stuck. What they get stuck on gets fixed in the manual, and, if needed, in the website too.

### Maker manual ("Jouw pagina op de website")

1. Inloggen: the inloglink in your mail, and what to do if no mail arrives
2. Your page at a glance: what visitors see and what you can change
3. Your name, a short introduction and profile photo
4. Adding text
5. Putting photos online (a photo album), and changing their order
6. Adding a YouTube or Vimeo video
7. Buttons to Instagram, YouTube and your own website
8. Moving parts of your page up or down, or hiding them for a while
9. Making things visible, or keeping them hidden until they're ready
10. Choosing your colour and cover photo
11. Asking for a different webadres
12. Good photos with your phone: light, background, landscape or portrait
13. What if something goes wrong? Who to ask

### Webmaster manual ("Beheer van de website")

1. Everything from the maker manual (webmasters are makers too)
2. Editing the general pages, in Dutch and English
3. The menu and the site-wide settings (address, contact details)
4. Inviting a new maker, and choosing their webadres
5. Handling a request for a different webadres
6. Taking a maker offline: what happens next (the 60 days, the message visitors see)
7. What you **can't** do: edit a maker's page. Why, and what to do instead
8. Helping makers: the ten most common questions and their answers
9. What to do if the website is down, and who to call

### Superadmin manual ("Sleutelhouder")

1. What a sleutelhouder is and when you're needed (rarely)
2. Inloggen, even after a long time away
3. Putting a removed maker back, deleting them right away (a privacy request), or postponing the deletion (up to 1 year)
4. Giving someone the webmaster or sleutelhouder role, or taking it away
5. **When William leaves:** the step-by-step handover, which links to the Succession checklist in `RUNBOOK.md` (STRATO, the daily task caller, Healthchecks.io, backups)
6. Where the passwords and accounts are kept
7. The warning emails you might get (from Healthchecks.io, or about a deletion due soon) and what to do about them

### Who writes and tests what: after go-live

The manuals are the **last item on the list** and are written **after the website is online** (D26). At launch, William helps makers get their first introduction online in person, and what makers ask during those sessions goes straight into the manuals.

| Manual | Written by | Tested by | Target |
|---|---|---|---|
| Maker (NL, EN) + A5 card | William | 1–2 makers who didn't sit with William at launch | Late October / November 2026 |
| Webmaster | William | Maartje | November 2026 |
| Superadmin | William | Arwin, doing every step himself | November 2026 (the access check itself happens on 17 Oct) |

**Before launch**, only the **word list** applies. The website's own buttons and text use plain words from the start. Everything else from this section follows after launch.

The manuals live in the repo (`docs/manuals/`) as Markdown with screenshots, and are published as help pages and PDFs. Whenever a screen changes, its screenshots are updated in the same change.

---

## 7. Authentication

- **Invite-only.** A webmaster invites an email address, optionally linked to a new or existing space, and sets the initial slug.
- **Magic link** by default: single-use, valid for 15 minutes, stored as a hash. A **password** (argon2id) is optional.
- Flask-Login and Flask-WTF (CSRF). The login and magic-link endpoints get a **DB-backed rate limiter** (`rate_limits` table): under CGI there's no in-memory store, and there's no Redis.
- Cookies are `Secure`, `HttpOnly` and `SameSite=Lax`, and the session is rotated on login.
- TOTP 2FA for webmasters and superadmins comes in phase 2.
- Transactional email goes through an EU provider (Brevo, Mailjet or Scaleway TEM) from the collective's domain, with SPF, DKIM and DMARC configured. Emails are sent in the recipient's `ui_lang`.

---

## 8. Public site

- Server-rendered, minimal JS, fast on mobile.
- One base theme using the dovetail logo and the collective's colours. Makers can set an accent colour and cover image.
- SEO:
  - Titles and descriptions per language, and `hreflang` on front pages.
  - `sitemap.xml` covering only live content.
  - Canonical URLs.
  - JSON-LD: `Organization` for the collective, `Person` for each maker.
- **Static page cache (D18)**, built 26 Sep 2026 (`app/public/cache.py`):
  - The first visit to a public page renders it as usual and stores the HTML as `<PAGE_CACHE_ROOT>/<url path>/index.html` (`/` → `index.html`, `/en/makers` → `en/makers/index.html`, `/jan` → `jan/index.html`). Later visits get the file.
  - The web server serves those files directly. On Profile B, `.htaccess` rewrite rules check for the file first and only fall back to CGI when it isn't there, so `PAGE_CACHE_ROOT` is `<web root>/_cache`. Under Gunicorn the app itself serves the file before touching the database.
  - Only plain `GET`s without a query string that return 200 are stored. 404s, the "no longer active" page and redirects never are, so hidden spaces always reach Python and get the proper 404 status.
  - **Invalidation: any committed change to content clears the whole cache.** This hooks into the database commit, so no save action can forget it. Logins, invites, memberships, the audit log, rate limits and task runs don't count as content. With fewer than 15 makers a full rebuild takes seconds, so the `page_cache` dependency table from the original plan isn't needed.
  - A generation token makes sure a page rendered during a change is never stored with the old content.
  - Every deploy clears the cache (`flask page-cache clear`, in the container entrypoint and `deploy.sh`), because templates may have changed. `flask page-cache warm` renders all pages ahead of visitors; the task runner calls it (D17).
  - Public pages contain nothing per visitor or per session: no CSRF token, and the interface language follows the URL or the maker (D27).
  - `PAGE_CACHE=0` switches it off. With `TEMPLATES_AUTO_RELOAD=1` (development), an edited template clears the cache on the next visit.

### Privacy (AVG/GDPR)

- No tracking. If there are analytics, they're cookieless (Plausible or Umami, self-hosted). With no tracking cookies, **no cookie banner** is needed; the language cookie is functional.
- YouTube via `youtube-nocookie.com` with **click-to-load**, and Vimeo with `dnt=1`.
- The privacy page (NL/EN) lists what's stored, the 60-day purge after removal, and the backup retention.
- Removal follows §3a.

---

## 9. Tech stack

| Layer | Choice |
|---|---|
| App | Python 3.12+, Flask 3, blueprints |
| ORM and migrations | SQLAlchemy 2.x, Alembic (Flask-Migrate) |
| Database | MariaDB 10.6+ (PyMySQL driver) |
| i18n | Flask-Babel (UI strings), per-language content tables |
| Validation | Pydantic v2 |
| Templates | Jinja2, HTMX, SortableJS, TipTap/Trix |
| CSS | Plain CSS with custom properties |
| Images | Pillow, pillow-heif |
| Scheduled jobs | One task runner (`flask run-tasks`): purge, expire tombstones, purge reminders, cache rebuild. How it's triggered depends on the profile (§10a) |
| Web server | **A:** Gunicorn behind Caddy (automatic ACME) · **B:** STRATO Apache + CGI, with SSL from STRATO |
| Packaging | **A:** Podman/Docker, `compose.yaml` (app, db, caddy, cron) · **B:** SFTP/rsync deploy script, dependencies in a vendored `lib/` folder |
| Tests | pytest, factory-boy; RBAC matrix tests and lifecycle tests (with time freezing) |

### Project layout

```
createur-cms/
├─ app/
│  ├─ __init__.py          # create_app()
│  ├─ models/
│  ├─ auth/                # login, magic link, invites, policy.py
│  ├─ public/              # front + /<slug> resolver (catch-all last)
│  ├─ admin/
│  │  ├─ space/            # maker editing
│  │  └─ site/             # webmaster editing, makers, slug approvals
│  ├─ lifecycle/           # remove, restore, postpone, purge, tombstones
│  ├─ blocks/              # one module per block type: schema, form, template
│  ├─ media/               # upload, processing, storage backend
│  ├─ translations/        # Babel .po/.mo (nl, en)
│  ├─ templates/
│  └─ static/
├─ migrations/
├─ tests/
├─ compose.yaml
└─ Containerfile
```

---

## 10. Hosting: Profile A (VPS / self-host), the fallback

- The app runs on William's own infrastructure: one VM or container host running `compose.yaml` with the app, MariaDB, Caddy and cron.
- **Ownership:** the collective owns the **domain** and the **email provider** account (D9). DNS points to William's host.
- **Portability**, so a move later is simple:
  - Everything is in compose, and all config is in `.env`.
  - Data is only in the MariaDB volume and the media volume.
  - Migrating to a collective-owned VPS means restoring the backup and changing DNS.
- **Backups:** a nightly `mariadb-dump` plus a media snapshot with **restic** to off-site storage, kept for 30 days. Test a restore before launch.
- **Monitoring:** an uptime check (Uptime Kuma), error reporting (GlitchTip, self-hosted), and **Healthchecks.io** as the dead man's switch for the daily tasks and backups (§10a).
### Options for a later move to a collective-owned server

| | **STRATO VPS Linux** | Hetzner Cloud | TransIP VPS | Managed EU PaaS (Scalingo, Clever Cloud) |
|---|---|---|---|---|
| Type | VPS (root access; runs compose) | VPS | VPS | PaaS (app + managed DB) |
| Price range | €4/month (1 vCore), €10/month (2 vCores) | About €4–8/month | About €5–10/month | About €15–40/month |
| Data centres | Germany | Germany / Finland | Netherlands | France / EU |
| Domain + email at same provider | ✅ Domains and mail hosting available | ❌ (DNS only) | ✅ | ❌ |
| Ops burden | Maintained by us: OS updates, backups | Same | Same | Low |
| Notes | William's preferred provider. The collective can hold the domain, mailbox and server in **one account**, which keeps D9 simple. The VPS runs Profile A. STRATO's shared webhosting runs Profile B instead (§10a). | Good API/Terraform support | Dutch provider, Dutch support | Least maintenance, highest cost |

**Preferred target if the site moves: STRATO VPS Linux, 2 vCores (€10/month).**
- 1 vCore (€4/month) can run the site for fewer than 15 makers.
- Images are processed during the upload itself (§5), and on a single core several makers uploading photos at once will slow the site down for visitors.
- With 2 vCores there's headroom for MariaDB, Caddy and the cron jobs alongside image processing.
- Check the RAM and storage per plan when ordering. Aim for at least 4 GB RAM.

- **Bus factor:**
  - A second superadmin: Arwin (D24).
  - A short `RUNBOOK.md` covering restart, restore, renewing access, **handing over the task caller** (§10a), and a **Succession** checklist for Arwin (§3).
  - A sealed-envelope copy of the credentials held by the collective.

---

## 10a. Profile B: STRATO shared webhosting ("Hosting Basic")

### The package

- **Hosting Basic:** €1/month for the first 12 months, then **€6/month**. No setup fee.
- **Includes:** 2 domains, 2 SSL certificates, 100 GB webspace, 6 GB mail space, 2 mailboxes, 25 MySQL/MariaDB databases, Python and Ruby, and SSH/SFTP.
- **Why it fits D9:** the collective can hold the domain, the mail (for the magic links) and the hosting in one STRATO account.

### What changes compared with Profile A

| Topic | Profile A (VPS / self-host) | Profile B (STRATO Basic) | How the design handles it |
|---|---|---|---|
| Database | MariaDB container | STRATO MariaDB/MySQL | Same engine everywhere (D16) |
| Python runtime | Gunicorn, a long-running process | **CGI**: Apache starts a new Python process for **every request** | Static page cache (D18), lazy imports, lean dependencies |
| TLS | Caddy/ACME | STRATO SSL certificates | — |
| Scheduling | cron → `flask run-tasks` | No cron guaranteed on Basic (see "Scheduling" below) | External scheduler, plus a fallback during page requests |
| Rate limiting, state | Could use memory | No shared memory between requests | DB tables (`rate_limits`, `task_runs`) |
| Media serving | Caddy, via the app | Apache serves files straight from webspace | Hidden spaces' media are moved out of the web root (see below) |
| Deploys | `git pull` + compose | SFTP/rsync + a vendored `lib/` folder + `flask db upgrade` over SSH | One `deploy.sh` for each profile |
| Email | EU transactional provider | STRATO mailbox via SMTP | Same code; SMTP settings in `.env` |
| Logs and errors | Container logs, GlitchTip | Limited logs | Errors sent to GlitchTip (self-hosted by William) over HTTPS |

### CGI: the main trade-off

Each uncached request starts Python and imports Flask, SQLAlchemy, Jinja and Babel. **Expect a few hundred milliseconds to over a second per request.** The spike below measures the real number. Visitors should rarely notice, because:

- **Public pages** are nearly always served as static files (D18). Python runs only for the first visit after a change, for 404 pages, and for language redirects.
- **Admin and login** run through CGI. A slightly slower admin is acceptable for fewer than 15 makers.
- **Imports are lazy.** Pillow is imported only in the upload handler, and admin-only modules only in admin routes.
- **FastCGI, if available:** if STRATO turns out to support `mod_fcgid`, the Python process stays warm between requests and most of the per-request startup cost goes away. That's a verification item for the spike, not something the plan relies on.

### Scheduling on shared hosting (D17)

According to STRATO's FAQ, cron jobs are available on the legacy platform only from **Hosting Advanced** upward, and aren't available yet on the newer platform. So the plan assumes **no cron on Basic**:

1. **Primary: the task API, called by William's cron job (D21).**
   - A cron job on one of William's servers calls `POST https://<domain>/api/tasks/run` once a day, e.g. at 03:15.
   - **Auth:** the request carries `X-Task-Timestamp` and `X-Task-Signature: HMAC-SHA256(secret, timestamp + body)`. The request is rejected if the timestamp is more than 5 minutes off (so it can't be replayed) or the signature doesn't match. The secret lives in `~/private/.env` on STRATO and on the caller only.
   - **Body (optional):** `{"tasks": ["purge", "expire_tombstones", "reminders", "cache_rebuild"]}`. When the body is empty, all due tasks run.
   - **Response:** JSON with each task's status, how many items it handled, how long it took, and `more_pending` if a batch limit was hit. The caller logs the response and exits non-zero on failure, so William's own monitoring catches it.
   - **Idempotent and locked.** It uses the same atomic `task_runs` claim as the fallback, so a manual call, the cron job and the fallback can never run the tasks at the same time.
   - Example caller (for the runbook):
     ```bash
     #!/usr/bin/env bash
     # /etc/cron.d/createur-tasks: 15 3 * * * createur /opt/createur/call-tasks.sh
     set -euo pipefail
     TS=$(date +%s); BODY='{}'
     SIG=$(printf '%s%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$CREATEUR_TASK_SECRET" -hex | awk '{print $2}')
     curl -fsS -X POST "https://<domain>/api/tasks/run" \
          -H "Content-Type: application/json" -H "X-Task-Timestamp: $TS" -H "X-Task-Signature: $SIG" \
          --data "$BODY"
     ```
2. **Fallback: a time-based check during normal traffic, not "every 100th visit".**
   - On an uncached request or an admin login, the app checks `task_runs`. If the last successful run was more than 24 hours ago, it tries to claim it with one atomic `UPDATE task_runs SET last_started_at = now() WHERE task = 'daily' AND last_started_at < now() - INTERVAL 1 DAY`.
   - If exactly one row is updated, that request runs the tasks. Every other request skips them, so the tasks run once per day and never twice at the same time.
   - A visit counter wouldn't work well here. With low traffic, "every 100th visit" could go days without firing. With a spike of traffic, it would fire several times in a row.
   - Cached pages never reach Python, which is why the fallback runs on uncached requests and admin logins. The external trigger is the real guarantee.
3. The tasks are **idempotent** and **finish quickly**: fewer than 15 spaces, file deletes, a few queries. That keeps them well under CGI time limits. If a batch is too big, it processes N items and continues on the next run.
4. **Monitoring with a dead man's switch (external).** The app can't warn that it *didn't* run, because an app that isn't running can't send anything. So an outside service watches for a missing signal:
   - After **every successful task run**, whether the API or the fallback triggered it, the app pings a **Healthchecks.io** check URL: `GET https://hc-ping.com/<uuid>`. A failed run pings `/<uuid>/fail` with the error summary.
   - Healthchecks.io is set to expect one ping a day, with a grace period of 24 hours, which gives 48 hours in total. If no ping arrives in that window, or a `/fail` ping comes in, **Healthchecks.io emails** the superadmins, and optionally the webmaster.
   - It's independent of STRATO and of William's server. If either one dies, the missing ping still triggers the alert.
   - Cost: the free Hobbyist plan (20 checks) is plenty. Healthchecks.io is also open source, so it can be self-hosted later, but then it must not run on the same server as the cron caller.
   - The ping URL goes in `.env` (`HEALTHCHECK_URL`). The Healthchecks.io account belongs to the collective, and alert recipients are managed there. It's part of the handover in the runbook.
   - The admin dashboard still shows the last successful run and what triggered it, for a quick look.
   - A second check can watch William's nightly backup script the same way.
5. **The fallback only runs when traffic reaches Python**, meaning uncached pages or admin logins. In a quiet week with no edits, it may not fire for several days. That's fine as a safety net (a purge could run a few days late, never early), but it's why the API caller is the primary mechanism.
6. **Handover:** if William leaves the collective, the cron job moves to someone else's server or to a free scheduler such as cron-job.org, and the HMAC secret is rotated. Rotating the secret means changing it in `.env` and giving the new value to the new caller. `RUNBOOK.md` has a "Task caller" section with the script above and these steps. Until the handover, the fallback keeps the tasks running.

### Hiding media on shared hosting

Apache serves uploaded files directly, so a hidden space's images would still load if someone had their URL. On hide, the space's media folder is **moved outside the web root** (`~/private/hidden-media/<space-id>/`). A restore moves it back, and a purge deletes it there. The static page files for that space are deleted at hide time too.

### Directory layout on STRATO

```
~/                            (SSH home)
├─ app/                       # Python code + vendored lib/ (NOT web-accessible)
├─ private/                   # .env, hidden media, cache build area
└─ <domain>/                  # web root
   ├─ .htaccess               # static-first rewrites, security headers, cgi rules
   ├─ cgi-bin/createur.cgi    # thin CGI/WSGI wrapper → app
   ├─ static/                 # CSS, JS, icons
   ├─ media/<space-id>/...    # public image variants
   └─ _cache/<lang>/<path>/index.html   # rendered pages
```

### Spike before committing (one evening)

Profile B depends on details STRATO doesn't document well, so verify these on a Basic package before building for it:

| # | Check | Go / no-go |
|---|---|---|
| S1 | Python version via SSH | **≥ 3.10.** Older versions block current Flask and Pydantic. Online guides show 3.8 on some STRATO servers |
| S2 | `pip install --target lib/` for Flask, SQLAlchemy, PyMySQL, Pillow, Babel | Pillow must install from a wheel; there's no compiler |
| S3 | A hello-world Flask app over CGI with SQLAlchemy and a DB query: measure cold response time | Under 1.5 s is acceptable, because public pages come from the cache |
| S4 | Is FastCGI (`mod_fcgid`) available? | Nice to have |
| S5 | `.htaccess` rewrites: static-first, fallback to CGI, a custom 404 status from CGI | Must work |
| S6 | Upload size and CGI time/memory limits | A 5 MB upload plus processing must succeed |
| S7 | Cron on this package, despite the FAQ | If yes, the external trigger becomes a backup |
| S8 | SMTP from a STRATO mailbox, and SPF/DKIM/DMARC on the domain | Magic links must reach Gmail and Outlook inboxes |
| S9 | MariaDB version and `CHECK` constraint support | CHECK enforced (MariaDB ≥ 10.2) |

**If S1, S2, S3 or S5 fails, Profile B is off the table** and the plan falls back to Profile A (a STRATO VPS or William's own infrastructure).

### Backups on Profile B

- STRATO's own backups, plus a nightly pull from William's server over SSH: `mariadb-dump` and an `rsync` of the media, then `restic` to off-site storage with 30-day retention.

---

## 10b. Proof of concept on a local VM (D19)

The PoC runs on a local VM at **no cost** and is set up to **behave like STRATO Hosting Basic**. Once the collective approves, deploying to STRATO should mean copying files, not porting code.

### VM setup: mimic STRATO, not a VPS

| Aspect | PoC VM setting | Why |
|---|---|---|
| OS | Debian 12 (or Ubuntu 24.04), minimal | — |
| Web server | **Apache 2.4 + `mod_cgi` + `mod_rewrite`**, `AllowOverride All` | Same as STRATO: CGI and `.htaccess` do the work |
| App user | Unprivileged `createur` user, **no sudo** in daily use | Catches anything that needs root |
| Layout | The same home-dir layout as §10a (`~/app`, `~/private`, `~/<domain>/`) | `deploy.sh` targets both with only a different host |
| Python | System Python, plus **pyenv with Python 3.10** as the floor; tests run on both | STRATO's version is unknown until the spike; 3.10 is the go/no-go floor (S1) |
| Dependencies | `pip install --target ~/app/lib`, **wheels only** (`--only-binary=:all:`) | Same as STRATO: no compiler |
| Database | MariaDB 10.6+ on the VM, `utf8mb4` | Same engine as STRATO (D16) |
| Scheduling | **No cron for the app user.** The task API is called from the host machine with the same `call-tasks.sh` script William will run on his server, and the fallback during page requests is enabled | Tests the Profile B scheduling path for real |
| Email | **Mailpit** on the VM catches all mail (magic links, notifications) in a web inbox | No SMTP account needed; nothing reaches real inboxes |
| TLS | Self-signed, or plain HTTP on the local network | STRATO provides SSL later |
| Access for the demo | **In person** on William's laptop, and **remotely** at `createur.<demolabs-domain>` (D23) | The collective can try it themselves before approving |

### Provisioning

- An **Ansible playbook** (`deploy/poc-vm.yml`) builds the VM: packages, Apache vhost, MariaDB database and user, Mailpit, pyenv, the app user and the directory layout.
- The same `deploy.sh` (rsync + `flask db upgrade` over SSH) deploys to the VM now and to STRATO later. Only the target host and `.env` change.
- `flask seed-demo` loads demo content: the collective's front page (NL/EN), 3 demo maker spaces, demo users for each role combination, and one hidden space and one tombstone, so the "no longer active" page can be shown.

### PoC scope: enough to get the collective's approval

**In:**
- The front page, `/makers` and 3 maker spaces with the theme and new logo, in NL/EN
- Login by magic link (visible in Mailpit), a maker editing only their own space, and a webmaster editing the front page
- Blocks: text, gallery, video (click-to-load), social icons
- Removing a maker: hide, the "no longer active" 404, then restore by the superadmin
- The static page cache, so the demo shows the speed visitors will get

**Out (deferred to Phase 1):** slug requests, articles, postponing the purge, backups, monitoring, quotas, SEO polish.

**Demo script:** a 10-minute walkthrough.
1. A visitor views the site.
2. A maker logs in, adds a gallery and publishes it.
3. A webmaster edits the front page and tries to edit a maker's page, which is refused.
4. The webmaster removes a maker and shows the 404 page.
5. The superadmin restores that maker.

### Remote demo on the demolabs domain (D23)

- **Hostname:** a subdomain such as `createur.<demolabs-domain>`, reverse-proxied to the PoC VM, with TLS from William's existing setup. It isn't a STRATO-like setting, but that doesn't matter for the demo.
- **Keep it private:**
  - Put it behind William's existing **Authelia** gateway (one-factor), with a shared demo account for the collective, or with a personal account for each member.
  - `X-Robots-Tag: noindex` and a `robots.txt` that disallows everything.
  - **Clearly marked as a demo:** a banner on every page ("Demo — not the real website").
- **Magic links don't work remotely**, because all mail lands in Mailpit on the VM. For remote testers:
  - The seed data gets **demo users with passwords** for each role combination: maker, maker + webmaster, superadmin.
  - A **demo login page** offers one-click "log in as Maker A / Maker B / Webmaster" buttons.
  - Both only work when `DEMO_MODE=1`. The flag can't be set in production: the app refuses to start if `DEMO_MODE` is on and the host isn't a demo host.
  - In person, William demonstrates the real magic-link flow with Mailpit on screen.
- **Reset:** remote testers will change and delete things. The demo has a nightly `flask seed-demo --reset` on the VM, plus a "reset demo" button for the superadmin.
- **Photos:** only use demo images you own or have rights to, or the makers' own work with their permission. The demo is behind a login, but it's still shared.
- **Take it down after approval:** once the site is live on STRATO, the subdomain is switched off.

### What the PoC can't prove

The STRATO-specific facts (S1–S9 in §10a) can only be verified on STRATO itself. The local VM reduces that risk, but doesn't remove it. That's why the **spike is the first step after approval**, before any content is entered. If it fails, the same code runs on Profile A (a STRATO VPS, €4–10/month).

---

## 11. Phasing: live at the opening (Sunday 18 October 2026)

**Goal (D20):** the website is live on the collective's own domain on STRATO, and is **announced at the opening**.

### Timeline

| When | What | Who |
|---|---|---|
| **Wed 23 Sep** (1 evening) | **PoC in VS Code:** Flask + MariaDB on the VM, magic link via Mailpit, RBAC, 3 demo makers, text, gallery, video and social blocks, remove → "no longer active" 404, demo seed | William |
| Thu 24 – Wed 30 Sep | Run the PoC under **Apache + CGI** on the STRATO-like VM (§10b), add the static page cache and the task runner, and keep building toward the launch scope. The code carries over either way | William |
| **~Thu 1 Oct** | **Demo to the collective** (in person, then a few days of remote access on the demolabs subdomain) → **approval** | William + collective |
| Fri 2 – Sat 3 Oct | The collective **orders STRATO Hosting Basic and registers the domain** in its own account (about 2 days) | Collective |
| Sat 3 – Sun 4 Oct | **Spike S1–S9** on the real package. If it fails, order a STRATO VPS (Profile A) the same day; the code runs unchanged | William |
| Mon 5 – Fri 9 Oct | Deploy, set up the STRATO mailbox for SMTP, SPF/DKIM/DMARC, **the cron job on William's server that calls the task API**, backups; privacy page; the webmasters fill the front page (NL/EN) | William + Maartje |
| **Sat 10 Oct** | **Invite all makers.** The invite email explains in plain words how the inloglink works. **William sits down with makers** to get their first introduction online together | William + Maartje |
| Sat 10 – Wed 14 Oct | Makers fill their spaces. William gives help on request | Makers |
| **Wed 14 Oct** | **Go/no-go** (see below) | William + collective |
| Thu 15 Oct | Content freeze for the launch: only fixes. **QR code** to the site for signs and flyers at the opening | William + Maartje |
| Sat 17 Oct | Final check on phone and desktop, a restore test from backup, and a **15-minute access check with Arwin**: can he log in to the site as superadmin, to STRATO and to Healthchecks.io, and does he know where the runbook is? | William + Arwin |
| **Sun 18 Oct** | **Announce the website live at the opening** | Collective |

### Launch scope (must work by 14 Oct)

- Front section NL/EN, `/makers`, maker pages; interface in NL/EN
- Magic-link login, invites (the webmaster sets the slug at invite), the RBAC policy with matrix tests
- Blocks: text, gallery, image, video (click-to-load), social icons, cta
- Removing a maker → hide → "no longer active" 404 → restore by the superadmin
- Static page cache (built), client-side image resize, the media pipeline
- Privacy page, nightly backups, uptime check
- Plain-language website text (the word list in §6a)

### Deliberately after the opening (safe to defer)

- **The purge job, postpone and tombstones.** The earliest possible purge is 60 days after the first removal, so mid-December at the earliest. They have to be live before any hidden space reaches its `purge_at`. The admin dashboard shows a warning if that date is getting close and the job isn't deployed.
- The slug request/approval flow (until then, the webmaster sets slugs at invite)
- Storage quotas, audit log UI, 2FA, SEO polish

### Fallback if the go/no-go on 14 Oct is "no"

The domain goes live anyway with the front page, `/makers` (names, photo and Instagram link for each maker, entered by the webmaster) and a "maker pages coming soon" notice. The opening announcement still happens, and the maker spaces follow in the weeks after. This fallback needs only the front section, which is built first.

### Critical path and risks

| Risk | Impact | Mitigation |
|---|---|---|
| Approval slips past ~1 Oct | Everything after it moves too | Keep building during the approval week; after approval only deploying and adding content remain |
| Spike fails (Python version, CGI) | Profile B unusable | STRATO VPS (€4–10/month) the same weekend. The code runs unchanged; only the web server setup differs |
| DNS/email not ready in time | Magic links don't arrive | Configure SPF/DKIM/DMARC on day 1 after the domain is registered, and test with Gmail and Outlook |
| Makers fill their spaces late | Empty pages at launch | Unpublished spaces don't show on `/makers`. Launch with the makers who are ready |

### After the opening: phase 2
- **Manuals** for makers, webmasters and superadmins (§6a), using what makers asked during their launch sessions with William
- Articles: collective news (NL/EN), maker articles, and the `articles` block
- Agenda/events
- Audit log UI, 2FA for webmasters and superadmins
- Co-member (duo) invites in the UI

### Phase 3 (nice-to-have)
- Contact form per maker (honeypot and rate limiting)
- Map block
- Move to a STRATO VPS (Profile A), if shared hosting becomes limiting

---

## 12. Open questions

None at the moment. All decisions are in §0.

---

## 13. Next steps

1. **Wed 23 Sep:** build the PoC evening in VS Code (scope in §10b).
2. Move the PoC onto Apache + CGI on the STRATO-like VM (Ansible playbook), and add the static cache and task runner.
3. Prepare the demo script, the demo seed (with password demo users) and the `createur.<demolabs-domain>` subdomain behind Authelia. Schedule the demo with the collective (~1 Oct).
4. Ask the collective now to line up the STRATO order and domain name, so the 2 days start right after approval.
5. Apply the plain-language word list (§6a) to the website's own text from the first screen onwards. The manuals themselves come after go-live.
