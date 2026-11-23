# Heroine artist: Codex CLI that draws word pictures for EnglishBot.
# It gets no bot secrets and no database; see worker.py for the shared-folder protocol.
FROM node:22-slim

ARG CODEX_VERSION=0.171.0

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@openai/codex@${CODEX_VERSION}" && npm cache clean --force

COPY worker.py /opt/heroine-artist/worker.py

USER node
ENV HOME=/home/node \
    HEROINE_DIR=/work

CMD ["python3", "-u", "/opt/heroine-artist/worker.py"]
