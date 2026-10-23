from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_complete_pr_collection_rejects_truncation_and_head_races() -> None:
    """Execute the collector against API responses, including a racing push."""
    import json
    import os
    import subprocess

    action = yaml.load((ROOT / "actions/collect-pr-changes/action.yml").read_text(), Loader=yaml.BaseLoader)
    script = action["runs"]["steps"][0]["with"]["script"]
    for case in ["complete", "truncated", "head-before", "head-after", "base-after", "api-failure"]:
        harness = r"""
const input = JSON.parse(process.env.COLLECTION_TEST);
const writes = {}, outputs = {};
const expected = {number: 1, head: {sha: 'head'}, base: {sha: 'base'}};
let gets = 0;
const { strictGithub } = require(process.env.GITHUB_REST_FAKE);
const github = strictGithub({pulls: {
  get: async () => {
    gets++;
    if (input.case === 'api-failure') throw new Error('API unavailable');
    return {data: {...expected, changed_files: input.case === 'truncated' ? 2 : 1,
      head: {sha: input.case === 'head-before' || input.case === 'head-after' && gets === 2 ? 'new' : 'head'},
      base: {sha: input.case === 'base-after' && gets === 2 ? 'new' : 'base'}}};
  }, listFiles: async () => ({data: []})
}}, async () => [{filename: 'docs/new.md', previous_filename: 'src/old.md', status: 'renamed'}]);
const context = {repo: {owner: 'owner', repo: 'repo'}, payload: {pull_request: expected}};
const core = {setOutput: (k,v) => outputs[k] = v, warning: () => {}};
const fs = {rmSync: p => delete writes[p], writeFileSync: (p,v) => writes[p] = v};
(async () => {
  await new (Object.getPrototypeOf(async function(){}).constructor)('github','context','core','require',input.script)(github,context,core,() => fs);
  process.stdout.write(JSON.stringify({writes,outputs}));
})();
"""
        result = subprocess.run(
            ["node", "-e", harness],
            env={
                **os.environ,
                "COLLECTION_TEST": json.dumps({"script": script, "case": case}),
                "GITHUB_REST_FAKE": str(ROOT / "tests/ci/github_rest_fake.cjs"),
            },
            capture_output=True,
            text=True,
            check=True,
        )
        evidence = json.loads(result.stdout)
        assert evidence["outputs"]["complete"] == ("true" if case == "complete" else "false")
        if case == "complete":
            assert evidence["writes"]["complete-pr-paths.txt"].splitlines() == ["docs/new.md", "src/old.md"]
            assert json.loads(evidence["writes"]["complete-pr-changes.json"])["head"] == "head"
        else:
            assert evidence["writes"] == {}
