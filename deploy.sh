#!/bin/sh
# Copy sources to phoenix and rebuild the container.
set -e
DEST=admawby@192.168.0.7
DIR=/volume1/homes/admawby/Docker/lifeboat
cd "$(dirname "$0")"
tar --exclude=data --exclude=__pycache__ --exclude=tests -cf - Dockerfile .dockerignore docker-compose.yml app static \
  | ssh "$DEST" "mkdir -p $DIR/data '/volume1/root/Lifeboat Restores' && tar -xf - -C $DIR"
ssh "$DEST" "cd $DIR && export PATH=\$PATH:/usr/local/bin && docker compose up -d --build 2>&1 | tail -5"
