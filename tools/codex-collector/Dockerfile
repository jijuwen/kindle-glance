FROM node:22-bookworm-slim
ARG CODEX_VERSION=0.158.0
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global @openai/codex@${CODEX_VERSION} \
    && useradd --system --uid 10001 collector \
    && mkdir -p /state /public /bridge /app \
    && chown -R collector:collector /state /public /bridge /app
WORKDIR /app
COPY service.py rpc.py subscriptions.py entrypoint.py smoke_rpc.py ./
USER collector
EXPOSE 8091
CMD ["python3", "entrypoint.py"]
