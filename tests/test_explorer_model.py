"""Run the Node tests of the explorer's model.js (skipped where Node is not installed)."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_model_js():
    run = subprocess.run(
        ["node", "--test", *sorted(str(p) for p in JS_TESTS.glob("*.test.mjs"))],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
