# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20

ARG TARGETARCH
ARG POWERSHELL_VERSION=7.4.21
ARG POWERSHELL_SHA256=3fc5e1567c450bd7bd5ae69ebb0a9a4a4e0418bbc36b0232cf6dd547f0bfc0eb
# Optional build-only CA for an enterprise HTTPS proxy. Verification stays on.
RUN --mount=type=secret,id=proxy_ca \
    test "${TARGETARCH:-amd64}" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git python3 age tini libicu72 libgssapi-krb5-2 tzdata \
    && cp /etc/ssl/certs/ca-certificates.crt /tmp/build-ca.pem \
    && if [ -f /run/secrets/proxy_ca ]; then cat /run/secrets/proxy_ca >> /tmp/build-ca.pem; fi \
    && curl --fail --location --cacert /tmp/build-ca.pem --retry 2 \
       "https://github.com/PowerShell/PowerShell/releases/download/v${POWERSHELL_VERSION}/powershell-${POWERSHELL_VERSION}-linux-x64.tar.gz" -o /tmp/powershell.tar.gz \
    && printf '%s  /tmp/powershell.tar.gz\n' "$POWERSHELL_SHA256" | sha256sum --check --strict \
    && mkdir -p /opt/powershell \
    && tar -xzf /tmp/powershell.tar.gz -C /opt/powershell \
    && chmod +x /opt/powershell/pwsh \
    && ln -s /opt/powershell/pwsh /usr/local/bin/pwsh \
    && NPM_CONFIG_CAFILE=/tmp/build-ca.pem npm install --global --no-audit --no-fund @openai/codex@0.159.2 \
    && rm -rf /var/lib/apt/lists/* /tmp/powershell.tar.gz /tmp/build-ca.pem /root/.npm

ENV NEWS_PYTHON=/usr/bin/python3 \
    NEWS_GMAIL_TRANSPORT=gmail_api \
    NEWS_DATA_DIR=/var/lib/newsflow/state \
    NEWS_SERVICE_ENABLED=false \
    POWERSHELL_TELEMETRY_OPTOUT=1 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --chown=node:node outputs/rss-news-monitor/ ./outputs/rss-news-monitor/
COPY --chown=node:node outputs/telegram-forwarder/ ./outputs/telegram-forwarder/
COPY --chown=node:node deploy/cloud/ ./deploy/cloud/
RUN mkdir -p /var/lib/newsflow \
    && chown node:node /var/lib/newsflow \
    && ln -s /var/lib/newsflow/state/work /app/work
USER node
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/app/deploy/cloud/worker.py"]
CMD ["run"]
