#!/usr/bin/env bash
# Samples the server while a load test runs: CPU (and time waiting for the disk), memory,
# network traffic, disk reads and open viewer connections, every few seconds, as CSV on
# stdout. The peaks are printed at the end (after --duration, or on Ctrl+C).
#
#   deploy/scripts/monitor_server.sh --duration 900 > /srv/backups/lms/monitor-500.csv
#   deploy/scripts/monitor_server.sh --interval 2 --interface eno1
#
# Reads /proc only: nothing to install. The interface defaults to the one with the default
# route; its link speed (if known) shows how close the network card is to its limit.
set -euo pipefail

INTERVAL=5
DURATION=0
IFACE=""
usage() { sed -n '2,10p' "$0"; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
    case "$1" in
        --interval) INTERVAL="${2:?}"; shift 2 ;;
        --duration) DURATION="${2:?}"; shift 2 ;;
        --interface) IFACE="${2:?}"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage 1 ;;
    esac
done
[[ "$INTERVAL" =~ ^[0-9]+$ && "$INTERVAL" -ge 1 ]] || { echo "--interval: whole seconds, at least 1" >&2; exit 1; }
[[ "$DURATION" =~ ^[0-9]+$ ]] || { echo "--duration: whole seconds" >&2; exit 1; }

if [ -z "$IFACE" ]; then
    IFACE="$(awk '$2 == "00000000" { print $1; exit }' /proc/net/route 2>/dev/null || true)"
    [ -n "$IFACE" ] || IFACE="$(awk -F: 'NR > 2 { gsub(/ /, "", $1); if ($1 != "lo") { print $1; exit } }' /proc/net/dev)"
fi
SPEED="$(cat "/sys/class/net/$IFACE/speed" 2>/dev/null || true)"
[[ "$SPEED" =~ ^[0-9]+$ && "$SPEED" -gt 0 ]] || SPEED=""

# printf "%.0f": mawk would print counters above 2^31 in exponent form, which bash cannot add.
cpu()  { awk '/^cpu / { printf "%.0f %.0f %.0f\n", $2 + $3 + $4 + $7 + $8 + $9, $5, $6 }' /proc/stat; }  # busy idle iowait
net()  { awk -v i="$IFACE" -F'[: ]+' '{ sub(/^ +/, "") } $1 == i { print $2, $10 }' /proc/net/dev; }  # rx tx bytes
disk() { awk '$3 ~ /^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$/ { r += $6 } END { printf "%.0f\n", r * 512 }' /proc/diskstats; }
mem()  { awk '/^MemTotal/ { t = $2 } /^MemAvailable/ { a = $2 } END { printf "%d\n", (t - a) / 1024 }' /proc/meminfo; }  # MB in use
# Established TCP connections on port 80 (state 01, local port 0050), IPv4 and IPv6.
conns() { cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | awk '$4 == "01" && $2 ~ /:0050$/ { n++ } END { print n + 0 }'; }

echo "# Campus LMS server monitor on $(hostname) from $(date '+%Y-%m-%d %H:%M:%S'), interface $IFACE${SPEED:+ ($SPEED Mbit/s link)}, every ${INTERVAL}s" >&2
echo "time,cpu_busy_pct,cpu_iowait_pct,mem_used_mb,net_tx_mbps,net_rx_mbps,disk_read_mbs,http_connections"

read -r b0 i0 w0 < <(cpu)
read -r rx0 tx0 < <(net)
d0="$(disk)"
peak_cpu=0 peak_wait=0 peak_tx=0 peak_disk=0 peak_conn=0 peak_mem=0
start=$SECONDS

summary() {
    {
        echo "# Peaks: CPU busy ${peak_cpu}% (waiting for the disk ${peak_wait}%), memory ${peak_mem} MB used,"
        echo "#        sent ${peak_tx} Mbit/s${SPEED:+ of $SPEED}, disk reads ${peak_disk} MB/s, ${peak_conn} open HTTP connections"
    } >&2
}
trap 'summary; exit 0' INT TERM

while :; do
    sleep "$INTERVAL"
    read -r b1 i1 w1 < <(cpu)
    read -r rx1 tx1 < <(net)
    d1="$(disk)"
    used="$(mem)"
    c="$(conns)"
    row="$(awk -v b="$((b1 - b0))" -v i="$((i1 - i0))" -v w="$((w1 - w0))" \
              -v rx="$((rx1 - rx0))" -v tx="$((tx1 - tx0))" -v d="$((d1 - d0))" -v s="$INTERVAL" 'BEGIN {
        all = b + i + w; if (all <= 0) all = 1
        printf "%.0f,%.0f,%.1f,%.1f,%.1f", 100 * b / all, 100 * w / all, tx * 8 / s / 1e6, rx * 8 / s / 1e6, d / s / 1e6
    }')"
    IFS=, read -r busy wait tx_m rx_m disk_m <<< "$row"
    echo "$(date '+%H:%M:%S'),$busy,$wait,$used,$tx_m,$rx_m,$disk_m,$c"
    peak_cpu=$(( busy > peak_cpu ? busy : peak_cpu ))
    peak_wait=$(( wait > peak_wait ? wait : peak_wait ))
    peak_mem=$(( used > peak_mem ? used : peak_mem ))
    peak_conn=$(( c > peak_conn ? c : peak_conn ))
    peak_tx="$(awk -v a="$tx_m" -v b="$peak_tx" 'BEGIN { print (a > b ? a : b) }')"
    peak_disk="$(awk -v a="$disk_m" -v b="$peak_disk" 'BEGIN { print (a > b ? a : b) }')"
    b0=$b1 i0=$i1 w0=$w1 rx0=$rx1 tx0=$tx1 d0=$d1
    if [ "$DURATION" -gt 0 ] && [ $((SECONDS - start)) -ge "$DURATION" ]; then
        summary
        exit 0
    fi
done
