"""Every script the app and the portfolio load must at least parse: one bad line (a variable declared twice)
once stopped the whole app from running while every Python test still passed."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
NODE = shutil.which("node")


def _scripts() -> list[tuple[str, str]]:
    out = [(f.name, f.read_text()) for f in sorted(STATIC.glob("*.js"))]
    for page in sorted(STATIC.glob("*.html")):
        for i, body in enumerate(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", page.read_text(), re.S)):
            out.append((f"{page.name} <script #{i + 1}>", body))
    return out


@pytest.mark.skipif(NODE is None, reason="node isn't installed")
@pytest.mark.parametrize("name,code", _scripts(), ids=[n for n, _ in _scripts()])
def test_script_parses(name, code, tmp_path):
    f = tmp_path / "s.mjs" if re.search(r"^\s*(import|export)\s", code, re.M) else tmp_path / "s.js"
    f.write_text(code)
    r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
    err = [line for line in r.stderr.splitlines() if "Error" in line or "^" in line or line.strip().startswith(("const", "let", "var"))]
    assert r.returncode == 0, f"{name}: " + " | ".join(err[:4])
