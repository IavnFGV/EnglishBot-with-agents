# Deploy

`englishbot` deploys independently into `/opt/services/englishbot` on the VPS.

External access does not come from this repository. The shared nginx reverse proxy in `/opt/infra` handles public traffic and proxies to this service through the external Docker network `edge`.

## Service shape

- This repo does not publish `80` or `443`.
- This repo does not issue certificates.
- `docker-compose.yml` connects the app to the external `edge` network.
- The app uses the network alias `englishbot-app`.
- The container uses `expose: 8080`, which is enough for nginx-to-container traffic on the shared Docker network.
- The bot keeps SQLite and logs on the VPS through `./data` and `./logs` bind mounts inside `/opt/services/englishbot`.

## VPS layout

Expected directory:

```text
/opt/services/englishbot
```

Before the first deploy, place a real `.env` file in that directory with the application secrets such as `TELEGRAM_BOT_TOKEN`. Do not store those secrets in the repository.

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

The workflow SSHes to the VPS, updates `/opt/services/englishbot`, rebuilds the image, and runs:

```bash
docker compose up -d --build
docker compose ps
```

## Verify on VPS

From `/opt/services/englishbot`:

```bash
docker ps
docker network inspect edge
docker compose logs -f
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
