#!/bin/sh
# Inner encoder used by make_test_videos.sh (runs on the host or in an Alpine container).
# Writes H.264 High / AAC, 1280x720, ~1.2 Mbps, 2 s keyframes, fast-start MP4 files with the
# lesson name and a running timestamp burned in, so seek/resume can be checked by eye; plus
# a PDF of notes and a PNG diagram for the demo catalogue.
set -eu

OUT="$1"
LONG_SECONDS="${2:-1920}"
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"

FONT=""
for candidate in /usr/share/fonts/dejavu/DejaVuSans.ttf /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf; do
    [ -f "$candidate" ] && FONT="$candidate" && break
done

encode() {
    key="$1"; seconds="$2"; label="$3"; freq="$4"
    target="$OUT/$key"
    if [ -f "$target" ]; then
        echo "exists   $key"
        return
    fi
    mkdir -p "$(dirname "$target")"
    filters="noise=alls=10:allf=t"
    if [ -n "$FONT" ]; then
        filters="$filters,drawtext=fontfile=$FONT:text='$label   %{pts\\:hms}':x=40:y=40:fontsize=44:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12"
    fi
    echo "encoding $key (${seconds}s)"
    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i "testsrc=size=1280x720:rate=30:duration=$seconds" \
        -f lavfi -i "sine=frequency=$freq:sample_rate=48000:duration=$seconds" \
        -vf "$filters" \
        -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p \
        -b:v 1100k -maxrate 1400k -bufsize 2800k -g 60 -keyint_min 60 -sc_threshold 0 \
        -c:a aac -b:a 128k -ac 2 \
        -movflags +faststart \
        "$target.part.mp4"
    mv "$target.part.mp4" "$target"
}

picture() {
    key="$1"; label="$2"
    target="$OUT/$key"
    if [ -f "$target" ]; then
        echo "exists   $key"
        return
    fi
    mkdir -p "$(dirname "$target")"
    filters="scale=1280:720"
    if [ -n "$FONT" ]; then
        filters="$filters,drawtext=fontfile=$FONT:text='$label':x=40:y=40:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=14"
    fi
    echo "drawing  $key"
    ffmpeg -hide_banner -loglevel error -y -f lavfi -i "testsrc2=size=1280x720" -frames:v 1 -vf "$filters" "$target.part.png"
    mv "$target.part.png" "$target"
}

notes() {
    key="$1"; title="$2"
    target="$OUT/$key"
    if [ -f "$target" ]; then
        echo "exists   $key"
        return
    fi
    PY=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys' >/dev/null 2>&1; then
            PY="$candidate"; break
        fi
    done
    if [ -z "$PY" ]; then
        echo "skipped  $key (needs Python to generate the PDF)"
        return
    fi
    mkdir -p "$(dirname "$target")"
    echo "writing  $key"
    "$PY" "$SCRIPTS/make_test_notes.py" "$target" "$title"
}

# Same folders as the app shows: <batch>/<class>/<subject>/<module>/<NN-name>.<ext>.
# Titles come from the seed manifest (backend/seed/demo_catalog.json).
B="batch-2026-27"
encode "$B/class12/computer-science/01-python-basics/01-variables-and-types.mp4" 180 "Class 12 CS - Lesson 1"       440
encode "$B/class12/computer-science/01-python-basics/02-python-functions.mp4"   480 "Class 12 CS - Lesson 2"       523
encode "$B/class12/computer-science/01-python-basics/03-loops.mp4"              120 "Class 12 CS - Lesson 3 DRAFT" 587
notes  "$B/class12/computer-science/01-python-basics/05-python-basics-notes.pdf" "Python Basics - Notes"
encode "$B/class12/mathematics/01-calculus/01-limits-and-continuity.mp4" "$LONG_SECONDS" "Class 12 Maths - Lesson 1" 659
encode "$B/class11/physics/01-motion/01-speed-and-velocity.mp4"                 180 "Class 11 Physics - Lesson 1"  698
picture "$B/class11/physics/01-motion/02-velocity-diagram.png" "Velocity diagram (demo image)"
echo "done"
