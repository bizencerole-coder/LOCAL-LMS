# M0 — Discovery and inventory

Fill this in before installing anything (PRD §11.1, §17 M0). **Exit criteria:** the team
knows which hardware will be used and has a backup plan before making storage changes.

## Server candidate

Recorded 16 Oct 2026 over SSH (old office PC reinstalled with OMV, hostname `openmediavaultlms`):

| Item | Value |
|---|---|
| Machine / role today | Old desktop PC, freshly installed as the OMV/LMS host (UEFI boot) |
| CPU model, cores | Intel Core i3-2100 @ 3.10 GHz, 2 cores / 4 threads (2011, VT-x present) |
| RAM | 7.7 GB |
| System disk (type, size, free) | Seagate ST1000DM010 1 TB HDD (7200 rpm, SATA); root 908 GB, 858 GB free; 7.9 GB swap |
| Video disk(s) (type, size, free, RAID) | **None separate** — videos will live on the system disk (`/srv/campus-lms/videos`); no RAID |
| Ethernet NIC speed | eno1, 1000 Mbps (Intel on-board) |
| Switch port speed it connects to | *to record on site* |
| OS / OMV version | Debian 13 (trixie), openmediavault 8.5.11-1 (updated 16 Oct 2026), kernel 7.2.6 |
| Docker installed? Version / manager (OMV compose plugin?) | *in progress*: OMV-Extras + openmediavault-compose |
| Current storage layout (shares, mount paths) | Single ext4 root; `openmediavault-sharerootfs` plugin so a shared folder `campus-lms` can sit at `/srv/campus-lms` |
| Existing data backed up? Where, by whom, date | Disk wiped by the OMV installer on 16 Oct 2026 (nothing to keep, per the owner) |
| UPS available? Runtime | *to record on site* |
| Owner approval to use it (name, date) | *to record* |
| Network address | DHCP `172.18.1.169/24` on `172.18.1.0/24`; static address or reservation still to set |
| Ports | LMS (Nginx) on **80**; OMV web UI moved to **8081** (`http://172.18.1.169:8081`) on 16 Oct 2026 because both default to 80; SSH 22; SMB share `campus-lms` for lesson files |

Capacity note: a single 7200 rpm HDD streams a few dozen 1.2 Mbps lessons comfortably but is
the first bottleneck for the 100+ client stages (random reads from many files); an SSD for
`/srv/campus-lms/videos` is the cheapest upgrade if the load tests show rebuffering.

Commands that help (Linux): `lscpu`, `free -h`, `lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL`,
`df -h`, `ethtool <iface> | grep Speed`, `ip -4 addr`, `cat /etc/os-release`,
`docker version`, `omv-confdbadm read conf.system.filesystem.mountpoint` (OMV).

## Network

| Item | Value |
|---|---|
| Campus subnet(s) and gateway | Office test network (16 Oct 2026): server segment `172.18.1.0/24` (gateway `172.18.1.1`), tablet/laptop Wi-Fi segment `172.18.2.0/23`. The router **NATs** Wi-Fi clients onto the server segment: Nginx sees every client as `172.18.1.1` (see the test report). Campus subnets still to record |
| Free static IP for the LMS host (confirm no conflict) | Currently DHCP `172.18.1.169`; ask the network admin for a reservation or a static address |
| Local DNS available? Proposed name (e.g. `lms.campus.lan`) | Not yet; the app and `MEDIA_BASE_URL` use the IP |
| SSID(s) tablets will use; client isolation on/off | Office: `OFFIZE-NET` (tablet reached the server, so no isolation). Campus SSIDs still to record |
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
