#!/bin/sh
# Inner encoder used by make_test_videos.sh (runs on the host or in an Alpine container).
# Writes H.264 High / AAC, 1280x720, ~1.2 Mbps, 2 s keyframes, fast-start MP4 files with the
# lesson name and a running timestamp burned in, so seek/resume can be checked by eye.
set -eu

OUT="$1"
LONG_SECONDS="${2:-1920}"

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

encode class12/computer-science/lesson-01.mp4       180 "Class 12 CS - Lesson 1"       440
encode class12/computer-science/lesson-02.mp4       480 "Class 12 CS - Lesson 2"       523
encode class12/computer-science/lesson-03-draft.mp4 120 "Class 12 CS - Lesson 3 DRAFT" 587
encode class12/mathematics/lesson-01.mp4  "$LONG_SECONDS" "Class 12 Maths - Lesson 1"  659
encode class11/physics/lesson-01.mp4                180 "Class 11 Physics - Lesson 1"  698
echo "done"
