# Deploy

`englishbot` is a service repo. It deploys as one Dockge stack into `/opt/dockge/stacks/englishbot`, while persistent runtime data lives outside the repo in `/srv/services/englishbot` and static runtime assets live in `/srv/service-static/englishbot`.

External routing stays outside this repository. The shared infra repo owns nginx, HTTPS, certificates, the service registry, and the central host scheduler.

## VPS layout

Stack source:

```text
/opt/dockge/stacks/englishbot
```

Persistent service data:

```text
/srv/services/englishbot/data
/srv/services/englishbot/logs
/srv/services/englishbot/backups
/srv/services/englishbot/build.env
```

`build.env` contains non-secret build metadata written atomically by GitHub Actions. Docker Compose reads it on every container creation, so a later manual recreate keeps the deployed version, commit, build time, ref, and environment. Bot secrets such as `TELEGRAM_BOT_TOKEN` remain only in the stack `.env` file.

Persistent static assets:

```text
/srv/service-static/englishbot
```

Backup sync target on the host:

```text
/srv/drive-sync/services/englishbot/backups
```

Registered host tasks are expected to be mirrored by infra into:

```text
/srv/scheduled-tasks.d/englishbot
```

## Container vs host responsibilities

Inside the container:

- The bot runs `python -m englishbot`.
- SQLite is used at `/app/data/englishbot.sqlite3`, backed by the host bind mount `/srv/services/englishbot/data`.
- App logs go to `/app/logs`, backed by `/srv/services/englishbot/logs`.
- The app writes one SQLite backup per UTC day (`daily__YYYY-MM-DD.sqlite3`, staged in `.partial/` first) to `/app/backups`, backed by `/srv/services/englishbot/backups`.
- Runtime media files live in `/app/assets`, backed by `/srv/service-static/englishbot`.
- The 10 newest user-uploaded bulk-edit workbooks are retained in `/app/data/bulk-edit/uploads` for diagnostics; older uploads are pruned automatically, while generated exports are temporary.

On the host:

- Dockge stores and runs the stack from `/opt/dockge/stacks/englishbot`.
- Infra nginx reaches the app through the external Docker network `edge` and the `englishbot-app` alias on port `8080`.
- The host scheduler must not create SQLite backups itself.
- The host scheduler only services files that already exist in `/srv/services/englishbot/backups`: copies them into `/srv/drive-sync/services/englishbot/backups` and prunes old files by retention.

## Docker Compose shape

`docker-compose.yml`:

- does not publish `80` or `443`
- exposes `8080` only to the shared Docker network
- bind-mounts `data`, `logs`, and `backups` from `/srv/services/englishbot/...`
- bind-mounts `assets` from `/srv/service-static/englishbot`
- passes build metadata env vars into the container for status/build reporting
- reads persistent runtime build metadata from `/srv/services/englishbot/build.env`

## Scheduled tasks

Service-owned scheduled task source of truth lives in this repo:

```text
infra/scheduled-tasks/
```

Current task:

```text
infra/scheduled-tasks/backup-maintenance.sh
```

Task config:

```text
infra/scheduled-tasks/backup-maintenance.env
```

That host-side task:

- reads backup files from `/srv/services/englishbot/backups`
- copies them into `/srv/drive-sync/services/englishbot/backups`
- keeps only the newest `30` files in each directory by default
- uses a shell-sourced `.env` file, so values with spaces such as cron expressions must be quoted

The task intentionally does not create SQLite backups. The app is responsible for producing backup files before the host task ever sees them.

## GitHub Actions deploy

Use a maintained Python 3.12 patch release for local validation (tested with
3.12.16). The old 3.12.2 interpreter fails while importing current aiogram/Pydantic
typing annotations; the container and CI use the current 3.12 release.

Workflow file:

```text
.github/workflows/deploy.yml
```

Required GitHub Actions secrets:

- `VPS_HOST`
- `VPS_USER`
- `VPS_PORT`
- `VPS_SSH_KEY`
- `VPS_HOST_FINGERPRINT`: SHA256 fingerprint of the SSH host key negotiated by the action, verified through an existing trusted connection (ECDSA on the current VPS).

Deploy behavior:

- every `push` to any branch runs tests only
- every `pull_request` to `main` runs tests only
- `push` to `main` or `workflow_dispatch` on `main` runs tests and a Python dependency vulnerability audit first, then deploys; manual runs on other branches never deploy
- deployments are serialized, verify the SSH host fingerprint, and fast-forward to the exact tested commit; conflicting server-local changes stop deployment rather than being discarded
- deploy clones or updates the repo in `/opt/dockge/stacks/englishbot`
- deploy ensures `/srv/services/englishbot/{data,logs,backups}` exists
- deploy atomically writes the current build metadata to `/srv/services/englishbot/build.env` before Compose starts
- deploy ensures `/srv/service-static/englishbot` exists
- deploy ensures `/srv/drive-sync/services/englishbot/backups` exists
- deploy bootstraps those host paths with `sudo` before running git operations as the SSH user
- deploy prints whether each key directory already existed or was created, plus `ls -ld` for the final ownership and mode state
- deploy copies `assets/images/no-image.png` from the checked-out repo into `/srv/service-static/englishbot/images/no-image.png` so fresh VPS assets keep the teacher-content fallback placeholder without app-side bootstrap logic
- deploy runs `docker compose build --pull`, then `docker compose up -d --no-build --wait --wait-timeout 120`; the health check requests `/healthz` on the internal port
- deploy verifies `infra/service.env` and calls `/usr/local/bin/infra-vps-register --card ... --service-dir ...` to refresh routing and service-owned tasks
- `.github/dependabot.yml` schedules weekly pip and GitHub Actions update PRs; enable Dependabot alerts separately in GitHub repository settings

Before the first successful deploy, create a real `.env` file on the VPS inside `/opt/dockge/stacks/englishbot`. Keep secrets such as `TELEGRAM_BOT_TOKEN` out of git.

If the first deploy creates the repo clone automatically, it will still stop until `.env` exists. After that, use `.env.example` from the cloned repo as the template for the real server-side `.env`.

## Verify on VPS

From `/opt/dockge/stacks/englishbot`:

```bash
docker compose ps
docker compose logs -f
docker network inspect edge
```

Useful host-side checks:

```bash
ls -la /srv/services/englishbot
ls -la /srv/services/englishbot/backups
ls -la /srv/drive-sync/services/englishbot/backups
```

## Infra route setup

Public routing still belongs to the infra repo. Register this service there with values like:

```text
DOMAIN=<service-domain>
UPSTREAM_HOST=englishbot-app
UPSTREAM_PORT=8080
```

## Optional learner Mini App

Set `ENGLISHBOT_MINI_APP_URL=https://<service-domain>/mini-app` in the stack `.env` after routing the service domain through the infra-owned HTTPS nginx route to `englishbot-app:8080`. The app uses the existing internal port and container; no host port or extra service is needed. Infra changes are required in the separate `infra-vps` repository: register this public domain and proxy `/mini-app` (including `/mini-app/api/`) to `englishbot-app:8080`, with the existing `/healthz` route preserved. This repository does not apply those infra changes.

Static files are packaged under `englishbot/mini_app_static/`. The API prefix is `/mini-app/api/sessions/{session_id}`. `GET` returns the current question or summary, `POST .../answer` applies an action, `GET .../media/{asset_id}` serves the current item's local image, and `GET .../tts` serves the current item's persisted voice variant when TTS is enabled. Every API and media request requires `X-Telegram-Init-Data`, verified with the bot token server-side. Health remains `GET /healthz`. Nginx must forward that header and must not cache authenticated API/media responses publicly.

For local development, run `python -m englishbot` and use the existing port 8080. A Telegram WebApp launch requires a publicly reachable HTTPS URL; use an HTTPS development tunnel and set `ENGLISHBOT_MINI_APP_URL` to its `/mini-app` URL. The bot creates the official inline WebApp button for each session, so BotFather Main Mini App registration and a menu button are not required for this version. Do not set the menu button to this URL yet: a menu launch has no session id and cannot open a question. If BotFather asks you to pair a website domain with the bot, use `/setdomain` for that HTTPS domain. Leave `ENGLISHBOT_MINI_APP_URL` empty to keep the original Telegram training launch with no interface choice. Do not put the bot token in the URL or frontend.
