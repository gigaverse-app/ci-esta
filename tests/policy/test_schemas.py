import json
from pathlib import Path

from ci_esta.policy.schemas import schemas


def test_published_schemas_match_runtime_contracts():
    root = Path(__file__).resolve().parents[2] / "docs/schemas/test-policy"
    for name, schema in schemas().items():
        assert json.loads((root / f"{name}.schema.json").read_text()) == schema
