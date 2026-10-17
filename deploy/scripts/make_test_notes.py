#!/usr/bin/env python3
"""Write a small multi-page PDF of demo notes (standard library only).

    python3 deploy/scripts/make_test_notes.py OUTPUT.pdf "Title"

Used by encode_test_videos.sh for the demo catalogue's "Python Basics: Notes".
"""

from __future__ import annotations

import sys

PAGES = [
    [
        "Python Basics - Notes",
        "",
        "Lesson 1: Variables and Types",
        "- A variable is a name that refers to a value: x = 42",
        "- Common types: int, float, str, bool, list, dict",
        "- type(x) tells you the type of a value",
        "- Names are case-sensitive: total and Total differ",
    ],
    [
        "Lesson 2: Python Functions",
        "",
        "- Define a function with def:",
        "    def area(width, height):",
        "        return width * height",
        "- Call it with arguments: area(3, 4) gives 12",
        "- A function without return gives None",
    ],
    [
        "Practice",
        "",
        "1. Store your name in a variable and print it.",
        "2. Write a function that returns the larger of two numbers.",
        "3. Write a function that counts the vowels in a word.",
        "",
        "Campus LMS demo notes - generated for testing.",
    ],
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build(title: str) -> bytes:
    pages = [list(lines) for lines in PAGES]
    pages[0][0] = title
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    count = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>")
    font_obj = 3 + 2 * count
    for i, lines in enumerate(pages):
        ops = ["BT", "/F1 26 Tf", "72 730 Td", f"({_escape(lines[0])}) Tj", "/F1 15 Tf", "0 -34 Td"]
        for line in lines[1:]:
            ops += [f"({_escape(line)}) Tj", "0 -24 Td"]
        ops += ["/F1 10 Tf", "0 -40 Td", f"(Page {i + 1} of {count}) Tj", "ET"]
        stream = "\n".join(ops)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    title = sys.argv[2] if len(sys.argv) > 2 else "Python Basics - Notes"
    with open(sys.argv[1], "wb") as handle:
        handle.write(build(title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
