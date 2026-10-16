#!/usr/bin/env bash
# Load the demo catalogue and demo students (backend/seed/demo_catalog.json).
# Prompts for the demo students' password (or pipe it in with --password-stdin).
# Safe to re-run: existing records are kept.
#
# Generate the demo videos first:
#   deploy/scripts/make_test_videos.sh "$VIDEO_ROOT"
set -euo pipefail
cd "$(dirname "$0")"
./lms-admin.sh seed-demo "$@"
./lms-admin.sh tree
