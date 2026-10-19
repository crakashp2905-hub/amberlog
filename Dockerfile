# The core has no runtime dependencies, so this image is the Python base plus a
# wheel and nothing else. Built in two stages only to keep the build backend out
# of the final layer.
FROM python:3.13-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY memory_fabric ./memory_fabric
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.13-slim
LABEL org.opencontainers.image.title="Memory Fabric" \
      org.opencontainers.image.description="Governed agent memory, valued by effect on outcomes." \
      org.opencontainers.image.source="https://github.com/crakashp2905-hub/memory-fabric" \
      org.opencontainers.image.authors="C R Akash Preetham" \
      org.opencontainers.image.licenses="LicenseRef-Proprietary"

COPY --from=build /dist/*.whl /tmp/
# The production cryptography profile: AES-256-GCM from the maintained
# `cryptography` library only, and a store refuses to open without it.
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[crypto]" && rm /tmp/*.whl
ENV MEMORY_FABRIC_CRYPTO_PROFILE=production

# The store is a SQLite file and the container is disposable: keep them apart,
# or the first `docker rm` takes the event log with it. The log is the source of
# truth.
#
# Content keys get a volume of their own, so a copy of the database volume is
# not enough to read content. Mount and back up both; losing /keys makes the
# content in /data unreadable, which is what erasure relies on and also what a
# careless `docker rm` would do.
VOLUME ["/data", "/keys"]
ENV MEMORY_FABRIC_DB=/data/store.db \
    MEMORY_FABRIC_KEYS=/keys

# Not root: the process only ever needs to read its own package and write one
# directory, and a governance layer that runs as root is a poor advertisement.
RUN useradd --create-home --uid 10001 fabric \
    && mkdir -p /data /keys && chown fabric /data /keys && chmod 700 /keys
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER fabric

EXPOSE 8765

# `serve` binds loopback by default and refuses to serve unauthenticated on any
# other address, which inside a container would mean nothing could reach it. So
# the published surface is explicit: bind all interfaces, keep token auth on,
# and let the operator decide what to expose the port to. The token is printed
# at startup; pass --token to supply your own. The entrypoint chooses key
# custody: external for a new store, in-database (with a warning) for an old one.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
