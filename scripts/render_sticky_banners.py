"""Compatibility entry point; canonical artwork is rendered by render_brand.py."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("render_brand.py")), run_name="__main__")
