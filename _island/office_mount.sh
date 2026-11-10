#!/bin/bash
# Mount the office folder over Tailscale SSH. Prints no secrets.
set -u
ENV_FILE="${MARC_CURSOR_ENV:-/home/rox/marc/cursor.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
MOUNT="${MARC_OFFICE_MOUNT:-/home/rox/office/work}"
SSH_HOST="${MARC_OFFICE_SSH:-}"
REMOTE_CWD="${MARC_OFFICE_CWD:-}"
KEY="${MARC_OFFICE_KEY:-/home/rox/.ssh/id_ed25519}"
mkdir -p "$MOUNT"
if [ -z "$SSH_HOST" ] || [ -z "$REMOTE_CWD" ]; then
  echo "office ssh not configured" >&2
  exit 0
fi
if command -v mountpoint >/dev/null 2>&1 && mountpoint -q "$MOUNT" && ls "$MOUNT" >/dev/null 2>&1; then
  exit 0
fi
if command -v fusermount >/dev/null 2>&1; then
  fusermount -u "$MOUNT" >/dev/null 2>&1 || true
fi
umount -l "$MOUNT" >/dev/null 2>&1 || true
if ! command -v sshfs >/dev/null 2>&1; then
  echo "sshfs missing" >&2
  exit 0
fi
OPTS="reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,StrictHostKeyChecking=accept-new"
if [ -f "$KEY" ]; then
  OPTS="${OPTS},IdentityFile=${KEY}"
fi
sshfs -o "$OPTS" "${SSH_HOST}:${REMOTE_CWD}" "$MOUNT" || true
