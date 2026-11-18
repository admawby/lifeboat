FROM python:3.12-alpine

ARG RESTIC_VERSION=0.19.1
ARG RESTIC_SHA256=f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c

RUN apk add --no-cache ca-certificates tzdata coreutils \
 && wget -qO /tmp/restic.bz2 "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_amd64.bz2" \
 && echo "${RESTIC_SHA256}  /tmp/restic.bz2" | sha256sum -c - \
 && bunzip2 -c /tmp/restic.bz2 > /usr/local/bin/restic && chmod 755 /usr/local/bin/restic && rm /tmp/restic.bz2 \
 && restic version

COPY app /app/app
COPY static /app/static
WORKDIR /app/app
ENV LIFEBOAT_DATA=/data LIFEBOAT_PORT=8850 PYTHONUNBUFFERED=1 TZ=America/New_York
EXPOSE 8850
HEALTHCHECK --interval=60s --timeout=10s CMD wget -qO /dev/null http://127.0.0.1:8850/api/overview || exit 1
CMD ["python", "server.py"]
