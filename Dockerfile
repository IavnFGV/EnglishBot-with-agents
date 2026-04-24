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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/logs

EXPOSE 8080

CMD ["python", "-m", "englishbot"]
