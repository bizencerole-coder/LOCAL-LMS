# Sample data

No content files are stored in the repository: video files (`*.mp4`, `*.m4v`) are git-ignored, and the demo notes and image are generated like the videos.

## Demo test files

`deploy/scripts/make_test_videos.sh <VIDEO_ROOT> [--short]` generates the seven files the
demo catalogue (`backend/seed/demo_catalog.json`) expects, in the same folders the app shows
(`<batch>/<class>/<subject>/<module>/<NN-name>.<ext>`, all under `batch-2026-27/`):

| File under `batch-2026-27/` | What | Seeded as |
|---|---|---|
| `class12/computer-science/01-python-basics/01-variables-and-types.mp4` | video, 3 min | published |
| `class12/computer-science/01-python-basics/02-python-functions.mp4` | video, 8 min | published |
| `class12/computer-science/01-python-basics/03-loops.mp4` | video, 2 min | draft (must stay invisible) |
| `class12/computer-science/01-python-basics/05-python-basics-notes.pdf` | PDF notes, 3 pages | published |
| `class12/mathematics/01-calculus/01-limits-and-continuity.mp4` | video, 32 min (5 min with `--short`) | published (30-minute test) |
| `class11/physics/01-motion/01-speed-and-velocity.mp4` | video, 3 min | published, Class 11 only |
| `class11/physics/01-motion/02-velocity-diagram.png` | image, 1280×720 | published, Class 11 only |

The PDF is written by `deploy/scripts/make_test_notes.py` (Python standard library only).

Each video is H.264 High + AAC, 1280×720, 30 fps, ~1.2 Mbps, 2-second keyframes, fast-start,
with the lesson name and a running `hh:mm:ss` timestamp burned in so seek and resume
accuracy (AC-06, ±10 s) can be checked by eye. Light noise is added so the bitrate is
closer to real lesson recordings than a plain test pattern would be.

The script uses a local `ffmpeg`, or downloads `ffmpeg` into a temporary `alpine:3.22`
container if none is installed.

## Real lessons

Use the profile in PRD §12 and check files before registering them:

```bash
python3 deploy/scripts/inspect_media.py --recursive /path/to/lessons
```

Example re-encode (validate on samples first; keep the original):

```bash
ffmpeg -i input.mp4 -c:v libx264 -preset medium -crf 23 -vf "scale='min(1280,iw)':-2" \
  -g 60 -c:a aac -b:a 128k -movflags +faststart output-720p.mp4
```

If a file is already H.264/AAC but not fast-start, re-mux without re-encoding:
`ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4`.
