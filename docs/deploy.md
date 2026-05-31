# Deploy

`englishbot` is a service repo. It deploys as one Dockge stack into `/opt/dockge/stacks/englishbot`, while persistent runtime data lives outside the repo in `/srv/services/englishbot`.

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
- SQLite backup files should be created by application code in `/app/backups`, backed by `/srv/services/englishbot/backups`.

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
- passes build metadata env vars into the container for status/build reporting

## Scheduled tasks

Service-owned scheduled task source of truth lives in this repo:

```text
scheduled-tasks/
```

Current task:

```text
scheduled-tasks/backup-maintenance.sh
```

That host-side task:

- reads backup files from `/srv/services/englishbot/backups`
- copies them into `/srv/drive-sync/services/englishbot/backups`
- keeps only the newest `30` files in each directory by default

The task intentionally does not create SQLite backups. The app is responsible for producing backup files before the host task ever sees them.

## GitHub Actions deploy

Workflow file:

```text
.github/workflows/deploy.yml
```

Required GitHub Actions secrets:

- `VPS_HOST`
- `VPS_USER`
- `VPS_PORT`
- `VPS_SSH_KEY`

Deploy behavior:

- every `push` to any branch runs tests only
- every `pull_request` to `main` runs tests only
- `push` to `main` or `workflow_dispatch` runs tests first, then deploys
- deploy clones or updates the repo in `/opt/dockge/stacks/englishbot`
- deploy ensures `/srv/services/englishbot/{data,logs,backups}` exists
- deploy ensures `/srv/drive-sync/services/englishbot/backups` exists
- deploy runs `docker compose up -d --build`
- deploy calls `/usr/local/bin/infra-vps-register-service-scheduled-tasks`

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
