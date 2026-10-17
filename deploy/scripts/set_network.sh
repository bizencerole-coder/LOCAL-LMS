#!/usr/bin/env bash
# Point an existing installation at a new network, e.g. after moving the server to
# another campus: new server address for playback URLs and/or new client subnets.
# Keeps the database, secrets, accounts, progress and videos.
#
#   deploy/scripts/set_network.sh --media-base-url http://10.20.0.10 --allow 10.20.0.0/16
#   deploy/scripts/set_network.sh --allow 192.168.5.0/24 --allow 192.168.6.0/24
#   deploy/scripts/set_network.sh --media-base-url ""     # playback URLs use whatever address each tablet typed
#   deploy/scripts/set_network.sh --login-gateway 172.18.1.1      # tablets share this address (NAT)
#   deploy/scripts/set_network.sh --clear-login-gateways
#   deploy/scripts/set_network.sh --share-path '\\10.20.0.10\campus-lms\videos'   # shown on the dashboard
#   deploy/scripts/set_network.sh --dry-run ...
#
# --login-gateway: an address (or range) that many tablets share because the Wi-Fi router
# translates addresses, or a load-test computer. It gets room for a whole school signing in
# at once (nginx/login_gateways.conf); accounts are still locked after wrong passwords.
#
# Afterwards, set the same address on each tablet (sign-in screen -> Server).
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
cd "$(dirname "$0")/.."

usage() { sed -n '2,18p' "$0"; exit "${1:-0}"; }
die() { echo "error: $*" >&2; exit 1; }

MEDIA_BASE_URL_SET=0
MEDIA_BASE_URL=""
ALLOW=()
GATEWAYS=()
CLEAR_GATEWAYS=0
SHARE_PATH_SET=0
SHARE_PATH=""
DRY_RUN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --media-base-url) MEDIA_BASE_URL_SET=1; MEDIA_BASE_URL="${2-}"; shift 2 ;;
        --allow) ALLOW+=("${2:?--allow needs a CIDR}"); shift 2 ;;
        --login-gateway) GATEWAYS+=("${2:?--login-gateway needs an address or CIDR}"); shift 2 ;;
        --clear-login-gateways) CLEAR_GATEWAYS=1; shift ;;
        --share-path) SHARE_PATH_SET=1; SHARE_PATH="${2-}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
done
[ $MEDIA_BASE_URL_SET -eq 1 ] || [ ${#ALLOW[@]} -gt 0 ] || [ ${#GATEWAYS[@]} -gt 0 ] || [ $CLEAR_GATEWAYS -eq 1 ] \
    || [ $SHARE_PATH_SET -eq 1 ] || usage 1
[ -f .env ] || die "deploy/.env not found: run deploy/install.sh first"

if [ $MEDIA_BASE_URL_SET -eq 1 ] && [ -n "$MEDIA_BASE_URL" ]; then
    MEDIA_BASE_URL="${MEDIA_BASE_URL%/}"
    [[ "$MEDIA_BASE_URL" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$ ]] \
        || die "--media-base-url must look like http://192.168.10.10 or http://lms.campus.lan[:port]"
fi
for cidr in "${ALLOW[@]}"; do
    [[ "$cidr" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]] || die "--allow: not an IPv4 address or CIDR: $cidr"
done
case "$SHARE_PATH" in *"'"*|*$'\n'*) die "--share-path must not contain quotes or line breaks" ;; esac
for cidr in "${GATEWAYS[@]}"; do
    [[ "$cidr" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]] || die "--login-gateway: not an IPv4 address or CIDR: $cidr"
done

run() { if [ $DRY_RUN -eq 1 ]; then echo "would  $*"; else echo "+ $*"; "$@"; fi; }
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [ $MEDIA_BASE_URL_SET -eq 1 ]; then
    current="$(grep -E '^MEDIA_BASE_URL=' .env | cut -d= -f2- || true)"
    echo "MEDIA_BASE_URL: '${current}' -> '${MEDIA_BASE_URL}'"
    if [ $DRY_RUN -eq 0 ]; then
        if grep -qE '^MEDIA_BASE_URL=' .env; then
            sed -i "s|^MEDIA_BASE_URL=.*|MEDIA_BASE_URL=${MEDIA_BASE_URL}|" .env
        else
            printf 'MEDIA_BASE_URL=%s\n' "$MEDIA_BASE_URL" >> .env
        fi
    fi
fi

if [ ${#ALLOW[@]} -gt 0 ]; then
    echo "nginx/allowlist.conf: allowing ${ALLOW[*]} (plus 127.0.0.1 and Docker's 172.16.0.0/12)"
    if [ $DRY_RUN -eq 0 ]; then
        mkdir -p backups
        cp nginx/allowlist.conf "backups/allowlist.conf.$STAMP" 2>/dev/null || true
        {
            echo "# Networks allowed to reach the LMS. Written by deploy/scripts/set_network.sh on $STAMP."
            echo "# Change with: deploy/scripts/set_network.sh --allow <cidr> ...   (previous copy in backups/)"
            echo "# Keep 172.16.0.0/12: Docker's own bridge networks use it (container healthchecks)."
            echo "allow 127.0.0.1;"
            echo "allow 172.16.0.0/12;"
            for cidr in "${ALLOW[@]}"; do echo "allow $cidr;"; done
            echo "deny all;"
        } > nginx/allowlist.conf
    fi
fi

if [ $SHARE_PATH_SET -eq 1 ]; then
    printf "CONTENT_SHARE_PATH: %s -> '%s'\n" "$(grep -E '^CONTENT_SHARE_PATH=' .env | cut -d= -f2- || true)" "$SHARE_PATH"
    if [ $DRY_RUN -eq 0 ]; then
        # Rewritten without sed: share paths are full of backslashes.
        { grep -v '^CONTENT_SHARE_PATH=' .env || true; [ -z "$SHARE_PATH" ] || printf "CONTENT_SHARE_PATH='%s'\n" "$SHARE_PATH"; } > .env.new
        cat .env.new > .env && rm -f .env.new
    fi
fi

if [ ${#GATEWAYS[@]} -gt 0 ] || [ $CLEAR_GATEWAYS -eq 1 ]; then
    if [ ${#GATEWAYS[@]} -gt 0 ]; then
        echo "nginx/login_gateways.conf: whole-school sign-in rate for ${GATEWAYS[*]}"
    else
        echo "nginx/login_gateways.conf: no shared addresses (every address: 10 sign-ins a minute)"
    fi
    if [ $DRY_RUN -eq 0 ]; then
        mkdir -p backups
        cp nginx/login_gateways.conf "backups/login_gateways.conf.$STAMP" 2>/dev/null || true
        {
            echo "# Addresses many tablets share (NAT) and load-test computers: 20 sign-ins a second"
            echo "# with bursts of 600 instead of 10 a minute. Written by deploy/scripts/set_network.sh"
            echo "# on $STAMP (previous copy in backups/)."
            for cidr in "${GATEWAYS[@]}"; do echo "$cidr 1;"; done
        } > nginx/login_gateways.conf
    fi
fi

# The API reads MEDIA_BASE_URL at start (recreated by `up -d` when .env changed); Nginx
# reads the allowlist at start (bind-mounted file, so a restart is enough).
run docker compose up -d
run docker compose restart nginx
if [ $DRY_RUN -eq 0 ]; then
    echo
    scripts/check_stack.sh || true
    echo
    if [ -n "$(grep -E '^MEDIA_BASE_URL=' .env | cut -d= -f2-)" ]; then
        echo "Tablets: sign-in screen -> Server -> $(grep -E '^MEDIA_BASE_URL=' .env | cut -d= -f2-)"
    else
        echo "Tablets: sign-in screen -> Server -> http://<this server's address>"
    fi
fi
