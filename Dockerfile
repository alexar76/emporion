# EMPORION — public-record facts for agents that trade.
# Build from the MONOREPO ROOT so oracle-core is in context:
#     docker build -f emporion/Dockerfile -t emporion .
ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE} AS base
WORKDIR /app

COPY oracles/core /app/core
COPY emporion /app/emporion

RUN pip install --no-cache-dir -e "/app/core[pqc,postgres]" -e /app/emporion

# The tests, runnable against a candidate image; not the default target.
FROM base AS test
RUN pip install --no-cache-dir pytest pytest-asyncio
CMD ["python", "-m", "pytest", "/app/emporion/tests", "-q"]

FROM base AS runtime
EXPOSE 9351
# Not root: the signing key lives in /data, owned by uid 10001.
RUN mkdir -p /data && chown -R 10001:10001 /data
ENV HOME=/tmp \
    EMPORION_PORT=9351 \
    EMPORION_SIGNING_KEY_PATH=/data/emporion_signing_key \
    ORACLE_CALLS=1 \
    ORACLE_DATA_DIR=/data
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9351/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "emporion.main"]
