FROM python:3.12-slim

ARG ENGLISHBOT_VERSION=dev
ARG ENGLISHBOT_GIT_COMMIT=unknown
ARG ENGLISHBOT_BUILD_TIME_UTC=unknown
ARG ENGLISHBOT_BUILD_REF=unknown
ARG ENGLISHBOT_ENV_NAME=production

LABEL org.opencontainers.image.title="englishbot" \
      org.opencontainers.image.version="${ENGLISHBOT_VERSION}" \
      org.opencontainers.image.revision="${ENGLISHBOT_GIT_COMMIT}" \
      org.opencontainers.image.created="${ENGLISHBOT_BUILD_TIME_UTC}" \
      org.opencontainers.image.ref.name="${ENGLISHBOT_BUILD_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENGLISHBOT_VERSION="${ENGLISHBOT_VERSION}" \
    ENGLISHBOT_GIT_COMMIT="${ENGLISHBOT_GIT_COMMIT}" \
    ENGLISHBOT_BUILD_TIME_UTC="${ENGLISHBOT_BUILD_TIME_UTC}" \
    ENGLISHBOT_BUILD_REF="${ENGLISHBOT_BUILD_REF}" \
    ENGLISHBOT_ENV_NAME="${ENGLISHBOT_ENV_NAME}"

WORKDIR /app

# Debian security fixes land here before the upstream python image is rebuilt.
# The build metadata ARGs above change on every deploy, so this re-runs each build.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.3,<27" "setuptools>=78.1.1,<81" \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/logs /app/backups

EXPOSE 8080

CMD ["python", "-m", "englishbot"]
