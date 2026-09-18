#!/usr/bin/env python3
"""Syntax-check every inline <script> block in index.html.

A duplicate `const` once shipped to production and, being a parse-time
error, silently disabled every control on the page. This check exists so
that class of bug fails the build instead.
"""
import pathlib
import re
import subprocess
import sys
import tempfile

BLOCK = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)

html = pathlib.Path("index.html").read_text(encoding="utf-8")
blocks = BLOCK.findall(html)
if not blocks:
    sys.exit("::error::no inline <script> block found in index.html")

failed = 0
for i, body in enumerate(blocks, 1):
    offset = html[: html.index(body)].count("\n") + 1
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        tmp = fh.name
    proc = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
    if proc.returncode != 0:
        failed = 1
        detail = proc.stderr.strip().splitlines()
        msg = next((l for l in detail if "Error" in l), "syntax error")
        print(f"::error file=index.html,line={offset}::inline script {i}: {msg}")
        print(proc.stderr)

if failed:
    sys.exit(1)
print(f"All {len(blocks)} inline script block(s) parse cleanly ✓")
