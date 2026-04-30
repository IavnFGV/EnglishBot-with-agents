# Deploy

`englishbot` deploys independently into `/opt/services/englishbot` on the VPS.

External access does not come from this repository. The shared nginx reverse proxy in `/opt/infra` handles public traffic and proxies to this service through the external Docker network `edge`.

This repository does not manage nginx, HTTPS, certificates, or anything inside `/opt/infra`.

## Service shape

- This repo does not publish `80` or `443`.
- This repo does not issue certificates.
- `docker-compose.yml` connects the app to the external `edge` network.
- The app uses the network alias `englishbot-app`.
- The container uses `expose: 8080`, which is enough for nginx-to-container traffic on the shared Docker network.
- The bot keeps SQLite and logs on the VPS through `./data` and `./logs` bind mounts inside `/opt/services/englishbot`.
- `docker-compose.yml` passes `ENGLISHBOT_VERSION`, `ENGLISHBOT_GIT_COMMIT`, `ENGLISHBOT_BUILD_TIME_UTC`, `ENGLISHBOT_BUILD_REF`, and `ENGLISHBOT_ENV_NAME` into the container so the status server and startup logs expose the deployed build.

## VPS layout

Expected directory:

```text
/opt/services/englishbot
```

Before the first successful deploy, place a real `.env` file in that directory with the application secrets such as `TELEGRAM_BOT_TOKEN`. Do not store those secrets in the repository.

Example setup on the VPS:

```bash
mkdir -p /opt/services/englishbot
cd /opt/services/englishbot
cat > .env
```

Paste the required variables, save the file, and then update it later in place when secrets change.

If this is a brand-new VPS and the repository has not been cloned there yet, let the first workflow run create `/opt/services/englishbot` and clone the repo. That first run will stop with a clear `.env` error. After that, you can use `.env.example` in the cloned repo as a reference while creating `/opt/services/englishbot/.env`.

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

Do not hardcode the VPS IP or hostname in the workflow. Keep those values in GitHub Actions secrets only.

CI behavior:

- Every `push` to any branch runs tests only.
- Every `pull_request` targeting `main` runs tests only.
- A `push` to `main` runs tests first, then deploys only if tests pass.
- `workflow_dispatch` also runs tests before deploy.

The test command is defined in the workflow as:

```bash
python -m pytest
```

The deploy job depends on the test job and SSHes to the VPS only after the test job succeeds. The SSH deployment logic itself stays the same: it updates `/opt/services/englishbot`, rebuilds the image, and runs:

```bash
docker compose up -d --build
docker compose ps 
```

## Repository clone access

The workflow currently clones with:

```bash
https://github.com/IavnFGV/EnglishBot-with-agents.git
```

That works with the repository's current public visibility.

If the repository is made private later, HTTPS clone from the VPS will fail unless one of these is added first:

- a token-backed Git clone setup on the VPS, or
- a workflow change to `git@github.com:OWNER/REPO.git` plus an SSH deploy key that is added to this repository

Do not switch the workflow to SSH clone unless the VPS user already has the corresponding repository deploy key configured.

## Run tests locally

From the repository root:

```bash
pip install -r requirements.txt
python -m pytest
```

## Verify on VPS

From `/opt/services/englishbot`:

```bash
docker compose ps
docker compose logs -f
docker network inspect edge
```

## Infra route setup

After this service is deployed, add a route in the infra repo with:

```text
registry/services/englishbot.env
```

Example values:

```text
DOMAIN=<service-domain>
UPSTREAM_HOST=englishbot-app
UPSTREAM_PORT=8080
```

That keeps public routing in the infra repo while this repo stays responsible only for the service container.
