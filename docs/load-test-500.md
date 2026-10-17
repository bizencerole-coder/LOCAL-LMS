# Testing 500 students watching at once

The plan for the load test at the client campus: the LMS server PC plugged into the
campus's wired network, this laptop on a wired port simulating students, and a few real
tablets on the campus Wi-Fi. Results go into the test report; no capacity is claimed
before they are measured (PRD §15.3, §20 F2).

## What this test can and cannot show

**It shows** whether the server (an i3-2100 with 7.7 GB RAM and one hard disk), its network
card and the wired network can deliver 500 video streams at once, at the lessons' real
bitrate, with sign-ins, progress saves and seeks: start-up times, stalls ("rebuffers"),
errors, and how busy the server was. The real tablets show what students would see on
the Wi-Fi while that load runs.

**It does not show** that the campus Wi-Fi can carry 500 tablets. That depends on how many
access points there are and where; it is estimated from a per-access-point measurement
and the access point count ([Wi-Fi for 500 students](#wi-fi-for-500-students)). Ten
tablets cannot prove it.

## What to expect before measuring

Every student watching streams the lesson's bitrate. For 500 students:

| Lesson bitrate | Example | 500 students | On a 1 Gbit/s network card (≈ 940 Mbit/s usable) |
|---|---|---:|---|
| 0.4 Mbit/s | 360p screen recording (the "Python Tutorial") | 200 Mbit/s | comfortable |
| 1.2 Mbit/s | 720p lessons (the test lessons) | 600 Mbit/s | fits |
| 1.5 Mbit/s | 720p, more detail | 750 Mbit/s | tight: little room for seeks and buffering |
| 2.5 Mbit/s | 1080p | 1,250 Mbit/s | does not fit: re-encode, or a 2.5 GbE card and switch port |

Check a lesson's bitrate with `python3 deploy/scripts/inspect_media.py lesson.mp4`.

- **Same lesson for a class**: after the first viewer the lesson is served from memory, so
  the hard disk hardly matters. **Different lessons**: the disk reads many files at once;
  an old hard disk may not keep up at 500 (an SSD would).
- **Sign-ins** are the heaviest work for the CPU (each password check is deliberately slow).
  500 students signing in within a minute takes the server several seconds to tens of
  seconds; the test measures it.

## Before the day

1. **Upgrade the server** to this version (sign-in limits, monitor): as `lmsadmin`,
   `cd ~/campus-lms && git pull --ff-only && deploy/scripts/upgrade.sh --no-pull`.
2. **Lessons**: put on the server the lessons the school will really use, at the bitrate
   it will use (or test lessons at the same bitrate).
3. **Bring**: the server PC with its power cable, this laptop, two Ethernet cables, the
   tablets (charged), an extension board.
4. **Ask the campus IT team** (fill in [m0-inventory.md](m0-inventory.md)):
   - two wired ports on the same switch, 1 Gbit/s: one for the server, one for the laptop;
   - a fixed address for the server (DHCP reservation or a static address);
   - the Wi-Fi's address range, and whether Wi-Fi traffic reaches the wired network with its
     own addresses or translated to one router address (NAT);
   - how many Wi-Fi access points there are, which models, where; whether client isolation
     is on (tablets must reach the server);
   - that a test may load the network for about an hour.

## Setting up at the campus

1. Move the server and re-point it: [setup guide §16](setup-guide.md#16-moving-the-server-to-another-site-pilot-at-another-campus).
2. On the server, check the network card's speed: `cat /sys/class/net/$(ip route show default | awk '{print $5}')/speed`
   should print `1000` (1 Gbit/s). `100` means a bad cable or switch port: fix that first.
3. Let the laptop sign in 500 students at once (otherwise Nginx allows 10 sign-ins a minute
   per address). Add the Wi-Fi's router address too if the tablets share one address:

   ```bash
   cd ~/campus-lms/deploy
   scripts/set_network.sh --login-gateway <laptop address> [--login-gateway <Wi-Fi router address>]
   ```

4. Create the simulated students on the server. Type a password when asked; it is not shown:

   ```bash
   read -rs PW && printf '%s\n' "$PW" | scripts/lms-admin.sh create-load-students --count 500 --class "Batch 2026-27/Class 12" --password-stdin
   ```

5. On the laptop (Git Bash, in the repository), type the same password; check the laptop's
   wired link is 1 Gbit/s and Wi-Fi is off:

   ```bash
   read -rs LMS_LOAD_PASSWORD && export LMS_LOAD_PASSWORD
   ```

## Running the stages

Run 50, 100, 250 and then 500 simulated students, 10 minutes each. For each stage:

1. On the server, start the monitor (it stops by itself after 12 minutes):

   ```bash
   deploy/scripts/monitor_server.sh --duration 720 > /srv/backups/lms/monitor-<N>.csv
   ```

2. On the laptop, start the students (all on one lesson, as a class would be):

   ```bash
   python deploy/scripts/load_test.py --base-url http://<server> --clients <N> --duration 600 \
       --ramp 0.2 --one-lesson --no-docker-stats --json load-<N>.json | tee load-<N>.md
   ```

3. Meanwhile, on the real tablets (signed in as ordinary students): play other lessons, seek,
   pause; note any slow start or stall, and on which access point the tablet was.
4. Write down the summary table, the monitor's peaks (printed at the end) and the tablet notes.

Stop at the first stage that fails the criteria below and run it once more to confirm.
Then repeat the largest stage that passed **without** `--one-lesson` (students spread over
all lessons): that tests the hard disk.

## Pass criteria (per stage)

- no server errors (5xx) and no client errors;
- start-up (authorise + first byte) p95 under 3 s; no rebuffers;
- no 429 at sign-in (the laptop is listed as a shared address) and no 503 `service_busy`;
- server: CPU busy under 80 %, network sent under 80 % of the link (800 Mbit/s on
  1 Gbit/s), waiting for the disk under 20 %;
- the real tablets start lessons within about 3 s and play without stalls.

## Afterwards

```bash
scripts/lms-admin.sh delete-load-students           # removes the accounts and their progress
scripts/set_network.sh --clear-login-gateways        # or re-run with only the Wi-Fi router's address
```

Keep `load-*.md`, `load-*.json` and the `monitor-*.csv` files for the report.

## If a stage fails

| What you see | Limit reached | What helps |
|---|---|---|
| Network sent near 900 Mbit/s, rebuffers grow | The server's network card | Lower bitrate (720p at about 1 Mbit/s), or a 2.5 GbE card and switch port |
| Waiting for the disk high, stalls mostly with different lessons | The hard disk | An SSD for the lessons, or more memory (16 GB keeps more lessons cached) |
| CPU busy near 100 % during the sign-in ramp | Password checks at sign-in | Start classes a few minutes apart (students stay signed in for 8 hours), more API workers (`WEB_CONCURRENCY`), a faster CPU |
| 503 `service_busy` | The API's admission limit | `WEB_CONCURRENCY`, `DB_POOL_SIZE` (troubleshooting.md) |
| 429 at sign-in | Many students on one address | `set_network.sh --login-gateway <that address>` |
| Server fine, tablets stall | The Wi-Fi | More or better-placed access points (below) |

## Wi-Fi for 500 students

- A modern 5 GHz access point (Wi-Fi 5 or 6) typically carries about **25–40 students**
  watching 1–1.5 Mbit/s video in one room; beyond that, everyone on it stalls. 500 students
  therefore need roughly **13–20 access points**, one per room or area, each **cabled** to
  the switch (not mesh), on non-overlapping channels, 5 GHz preferred.
- Measure one access point: put all the tablets you have on one access point, play while
  the simulated load runs, and note when stalls start. The planning figure above still
  needs the access point's data sheet or more devices to confirm.
- The Wi-Fi's address range must have more than 500 free addresses (a /23 has 510).
- Tablets must reach the server: no client isolation between Wi-Fi and the server, and a
  fixed server address (or a local DNS name).
- If the router translates all Wi-Fi addresses to one (NAT), list that address with
  `--login-gateway`; better, route the Wi-Fi range to the server without translation.

## Results

| Stage | Lesson mode | Start-up p50 / p95 | Rebuffers | Errors / 429 / 503 | CPU peak | Network peak | Disk wait peak | Tablets | Pass |
|---|---|---|---|---|---|---|---|---|---|
| 50 | one lesson | | | | | | | | |
| 100 | one lesson | | | | | | | | |
| 250 | one lesson | | | | | | | | |
| 500 | one lesson | | | | | | | | |
| (largest passing) | spread | | | | | | | | |
