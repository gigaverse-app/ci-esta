import json

from ci_esta.policy.resource_cli import main


def test_json_resource_boundary_preserves_capability_and_pin_constraints(tmp_path):
    registry = tmp_path / "registry.json"
    requirements = tmp_path / "requirements.json"
    output = tmp_path / "placement.json"
    registry.write_text(
        json.dumps(
            {
                "redis": {
                    "name": "redis",
                    "providers": [
                        {"name": "fake"},
                        {"name": "real", "capabilities": ["lua"], "runner_secrets": ["REDIS_PASSWORD"]},
                    ],
                }
            }
        )
    )
    requirements.write_text(json.dumps({"lua-test": [{"resource": "redis", "capabilities": ["lua"]}]}))
    args = ["--registry", str(registry), "--requirements", str(requirements), "--output", str(output)]
    assert main(args) == 1
    assert json.loads(output.read_text())["work"]["lua-test"]["placement"] is None
    assert main([*args, "--available", "REDIS_PASSWORD"]) == 0
    placement = json.loads(output.read_text())["work"]["lua-test"]["placement"]
    assert placement["secrets"] == ["REDIS_PASSWORD"]
    assert placement["mode"] == "runner"
    assert json.loads(output.read_text())["work"]["lua-test"]["providers"][0]["name"] == "real"
    requirements.write_text(
        json.dumps({"lua-test": [{"resource": "redis", "provider": "fake", "capabilities": ["lua"]}]})
    )
    assert main([*args, "--available", "REDIS_PASSWORD"]) == 1
