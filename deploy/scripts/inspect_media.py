#!/usr/bin/env python3
"""Check MP4 files against the playback profile (H.264 + AAC, fast start).

Needs only Python 3.10+, no database or containers, so it can run directly on the
storage host while preparing content:

    python3 deploy/scripts/inspect_media.py /srv/campus-lms/videos/class12/**/*.mp4
    python3 deploy/scripts/inspect_media.py --recursive /srv/campus-lms/videos

Exit code 1 if any file is unreadable or has problems.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

BACKEND_APP = Path(__file__).resolve().parents[2] / "backend" / "app"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BACKEND_APP / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--recursive", "-r", action="store_true", help="scan directories for .mp4/.m4v")
    args = parser.parse_args()

    files: list[str] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir() and args.recursive:
            files += [str(p) for p in sorted(path.rglob("*")) if p.suffix.lower() in (".mp4", ".m4v")]
        else:
            files.append(raw)

    return _load("mp4info").report(files)


if __name__ == "__main__":
    sys.exit(main())
