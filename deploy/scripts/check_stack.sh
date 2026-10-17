#!/usr/bin/env bash
# Operator check (FR-09): which layer is failing — containers, Nginx, API, database,
# storage, or the network between tablets and server?
#
#   deploy/scripts/check_stack.sh                    # uses the address Nginx publishes (from compose/.env)
#   deploy/scripts/check_stack.sh http://192.168.10.10
#
# Exit code 0 when every check passes, 1 otherwise (usable from cron or monitoring).
set -uo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
cd "$(dirname "$0")/.." || exit 2

fails=0
fail() { echo "FAIL  $*"; fails=$((fails + 1)); }
section() { printf '\n== %s ==\n' "$1"; }
# Value from .env unless the shell already sets it (Compose precedence); strips CR and quotes.
env_get() {
    local name="$1" value
    value="${!name:-}"
    if [ -z "$value" ] && [ -f .env ]; then
        value="$(grep -E "^$name=" .env | tail -1 | cut -d= -f2- | tr -d '\r"'"'")"
    fi
    printf '%s' "$value"
}

if [ -n "${1:-}" ]; then
    BASE="$1"
else
    # Ask Compose what Nginx actually publishes; fall back to .env, then defaults.
    published="$(docker compose port nginx 80 2>/dev/null | tr -d '\r' | tail -1)"   # e.g. 0.0.0.0:8080
    host="${published%:*}"; port="${published##*:}"
    [ -n "$port" ] || port="$(env_get LMS_HTTP_PORT)"
    [ -n "$host" ] || host="$(env_get LMS_HTTP_BIND)"
    case "$host" in ""|0.0.0.0|"*"|"::"|"[::]") host=127.0.0.1 ;; esac
    BASE="http://$host:${port:-80}"
fi

probe() {
    local name="$1" url="$2" code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url")"
    if [ "$code" = "200" ]; then echo "OK    $name ($url)"; else fail "$name ($url) -> HTTP $code"; fi
}

section "Containers"
docker compose ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'
docker compose ps -a --format '{{.Service}} {{.State}} {{.Health}}' | while read -r svc state health; do
    if [ "$state" != "running" ] || [ "$health" = "unhealthy" ]; then echo "FAIL  container $svc is $state ${health:+($health)}"; fi
done | tee /tmp/check_stack_containers.$$ ; [ -s /tmp/check_stack_containers.$$ ] && fails=$((fails + 1)); rm -f /tmp/check_stack_containers.$$

section "HTTP endpoints ($BASE)"
probe "nginx"            "$BASE/nginx-health"
probe "api process"      "$BASE/health"
probe "api dependencies" "$BASE/ready"
curl -s --max-time 5 "$BASE/ready"; echo

section "Database"
docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' || fail "pg_isready"

section "Video storage"
VIDEO_ROOT="$(env_get VIDEO_ROOT)"
if [ -n "$VIDEO_ROOT" ] && [ -d "$VIDEO_ROOT" ]; then
    echo "VIDEO_ROOT=$VIDEO_ROOT"
    content_files="$(find "$VIDEO_ROOT" -path "$VIDEO_ROOT/.*" -prune -o -type f \( -iname '*.mp4' -o -iname '*.m4v' \
        -o -iname '*.pdf' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \) -print | wc -l)"
    echo "Content files (videos, notes, images): $content_files"
    df -h "$VIDEO_ROOT" | tail -1
else
    fail "VIDEO_ROOT '$VIDEO_ROOT' is not a directory on this host"
fi
docker compose exec -T api python -m app.cli check-media > /tmp/check_stack_media.$$ 2>&1
media_rc=$?
tail -5 /tmp/check_stack_media.$$; rm -f /tmp/check_stack_media.$$
[ $media_rc -eq 0 ] || fail "check-media reported missing or unreadable files"

section "Configuration"
if [ -z "$(env_get MEDIA_BASE_URL)" ]; then
    echo "note  MEDIA_BASE_URL is empty: playback URLs use whatever address each tablet typed (fine on a LAN; set it for a fixed hostname)"
fi

section "Recent errors (last 30 minutes)"
# Matches the text format's level column and the JSON format's level field.
docker compose logs --since 30m api 2>&1 | grep -E '^[^|]*\| [0-9T:-]+Z (CRITICAL|ERROR|WARNING) |"level": ?"(CRITICAL|ERROR|WARNING)"' | tail -10
docker compose logs --since 30m nginx 2>&1 | grep -E '"status":(4|5)[0-9]{2}|\[(error|crit)\]' | tail -10

section "Network"
echo "Server addresses (tablets must reach one of these):"
addrs=""
if hostname -I >/dev/null 2>&1; then
    addrs="$(hostname -I)"
elif command -v ip >/dev/null 2>&1; then
    addrs="$(ip -4 -o addr show scope global | awk '{sub(/\/.*/, "", $4); print $4}')"
elif command -v ipconfig >/dev/null 2>&1; then   # Windows / Git Bash (development only)
    addrs="$(ipconfig | tr -d '\r' | grep -a 'IPv4' | sed 's/.*: *//')"
    echo "  (from ipconfig; use the Wi-Fi/LAN adapter address, not the vEthernet/WSL ones)"
fi
if [ -n "${addrs//[[:space:]]/}" ]; then
    printf '%s\n' $addrs | sed 's/^/  /'
else
    echo "  could not determine (hostname -I / ip / ipconfig unavailable)"
fi
echo "If tablets cannot connect but the checks above pass: check Wi-Fi client isolation,"
echo "the SSID/VLAN, the host firewall, and nginx/allowlist.conf."

echo
if [ $fails -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "$fails CHECK(S) FAILED"; fi
exit $(( fails > 0 ))
