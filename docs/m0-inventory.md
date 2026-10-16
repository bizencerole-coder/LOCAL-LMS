# M0 — Discovery and inventory

Fill this in before installing anything (PRD §11.1, §17 M0). **Exit criteria:** the team
knows which hardware will be used and has a backup plan before making storage changes.

## Server candidate

| Item | Value |
|---|---|
| Machine / role today | |
| CPU model, cores | |
| RAM | |
| System disk (type, size, free) | |
| Video disk(s) (type, size, free, RAID) | |
| Ethernet NIC speed | |
| Switch port speed it connects to | |
| OS / OMV version | |
| Docker installed? Version / manager (OMV compose plugin?) | |
| Current storage layout (shares, mount paths) | |
| Existing data backed up? Where, by whom, date | |
| UPS available? Runtime | |
| Owner approval to use it (name, date) | |

Commands that help (Linux): `lscpu`, `free -h`, `lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL`,
`df -h`, `ethtool <iface> | grep Speed`, `ip -4 addr`, `cat /etc/os-release`,
`docker version`, `omv-confdbadm read conf.system.filesystem.mountpoint` (OMV).

## Network

| Item | Value |
|---|---|
| Campus subnet(s) and gateway | |
| Free static IP for the LMS host (confirm no conflict) | |
| Local DNS available? Proposed name (e.g. `lms.campus.lan`) | |
| SSID(s) tablets will use; client isolation on/off | |
| AP models and count (≈11–20), controller | |
| AP uplink speeds / PoE switch model | |
| Switch between server and APs (model, uplink speed) | |
| WAN link can be disconnected for testing? How | |
| Firewall / VLANs in place | |

## Test tablets

| # | Model | Android version | RAM | Wi-Fi standard | Notes |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |

## Sample content

| File | Duration | Resolution | Codec (inspect_media.py) | Bitrate | Fast start | Readability of text/code |
|---|---|---|---|---|---|---|
| | | | | | | |

## Decisions (PRD §24)

| # | Decision | Choice | Decided by / date |
|---|---|---|---|
| 1 | Reuse OMV host or new server | | |
| 2 | OMV hosts the Compose services, or storage only | | |
| 4 | Local DNS name and subnet | | |
| 6 | Encoding profile after readability check | | |
| 7 | Admin web UI needed for the demo, or CLI is enough | | |

Already decided in the prototype code (revisit only if testing shows a problem):
player = `video_player`/ExoPlayer (#3), media authorization = Nginx signed URLs (#5).
