"""Print the public selector requirement owned by this checkout's pyproject."""

import tomllib
from pathlib import Path

dependencies = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())["project"][
    "dependencies"
]
requirements = [item for item in dependencies if item.startswith("pytest-selective @ ")]
if len(requirements) != 1:
    raise ValueError("pyproject.toml must declare exactly one pytest-selective dependency")
print(requirements[0])
