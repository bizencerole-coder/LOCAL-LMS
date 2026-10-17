#!/usr/bin/env bash
# Generate the demo files (videos, PDF notes, an image) referenced by backend/seed/demo_catalog.json.
#
#   deploy/scripts/make_test_videos.sh /srv/campus-lms/videos          # includes a 32-minute lesson
#   deploy/scripts/make_test_videos.sh /srv/campus-lms/videos --short  # long lesson cut to 5 minutes
#
# Uses a local ffmpeg if installed, otherwise an Alpine container (Docker required).
# Existing files are left untouched.
set -euo pipefail

OUT="${1:?usage: $0 VIDEO_ROOT [--short]}"
LONG_SECONDS=1920
[ "${2:-}" = "--short" ] && LONG_SECONDS=300

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

if command -v ffmpeg >/dev/null 2>&1; then
    sh "$SCRIPT_DIR/encode_test_videos.sh" "$OUT" "$LONG_SECONDS"
else
    echo "ffmpeg not found locally; using a temporary Alpine container"
    # The container runs as root; give the new folders and files back to the caller
    # afterwards (on Docker Desktop the chown is a no-op and may fail; that is fine).
    HOST_IDS="$(id -u):$(id -g)"
    # MSYS_NO_PATHCONV stops Git Bash on Windows from rewriting the container paths.
    MSYS_NO_PATHCONV=1 docker run --rm \
        -v "$OUT:/out" \
        -v "$SCRIPT_DIR:/scripts:ro" \
        alpine:3.22 \
        sh -c "apk add --no-cache --quiet ffmpeg font-dejavu python3 >/dev/null && sh /scripts/encode_test_videos.sh /out $LONG_SECONDS; rc=\$?; chown -R $HOST_IDS /out/batch-2026-27 2>/dev/null || true; exit \$rc"
fi
