# Let your agent find and remove wasted CI work

Give your coding agent this prompt from the repository you want to improve:

```text
Read https://raw.githubusercontent.com/gigaverse-app/ci-esta/main/skills/ci-esta/SKILL.md
and use it to measure this repository's GitHub Actions bottlenecks. Implement
the smallest useful improvement and verify it. For Python test selection,
also use pytest-selective's skill. Preserve required gates and full checkpoints;
report elapsed time, runner-seconds, run identities and remaining limitations.
```

The [skill](../skills/ci-esta/SKILL.md) is portable Markdown. It starts with
read-only measurement, distinguishes slow jobs from startup/admission overhead,
then chooses routing, caching, supersession or carefully justified receipt reuse.
CI-esta supports GitHub Actions for any application language. It does not turn a
non-GitHub CI provider into GitHub Actions or require your application to use Python.

## Optional installation

With Node.js 22.20+ and the [open skills CLI](https://github.com/vercel-labs/skills),
run from your target project and choose your coding agent:

```bash
npx skills add gigaverse-app/ci-esta --skill ci-esta
npx skills add gigaverse-app/pytest-selective --skill pytest-selective
```

The second skill is useful for Python pytest projects; skip it for other suites.
You can also copy the complete `skills/ci-esta/` folder into your agent's skill
directory, including `references/`. Review the source/revision when installing
or updating. Skills ship in these Git repositories; installing the Python CLI
does not automatically install instructions into your coding agent.

Merge this into an existing `AGENTS.md` if your agent uses repository instructions:

```markdown
## CI optimization
Use the CI-esta skill to inspect GitHub Actions timing before changing admission.
Keep the reporter outside validation, preserve required gates and execute on
uncertain evidence. Use pytest-selective for Python dependency-based selection.
Publish measured elapsed/runner time, run identities and preserved checks;
do not equate skipped tests, green workflows or rounded cost estimates with proof.
```

## Useful results, with receipts

A [real report](benchmarks/2026-10-22.md) exposed a **279s Windows job in a 295s
validation path**. Its independent observer cost 19 runner-seconds. A separate
matched pytest-selective README experiment cut runner time **627s to 48s (92.3%)**.
The latter is selection/input-routing savings, not CI-esta receipt-reuse savings.
Use those examples to structure a measurement, not to promise the same result.

Expect a small reviewable change and a before/after table. The agent should keep
reporting useful even when reuse is unsuitable, declare inaccessible CI data as
unmeasured, and leave conformance validators attached to the work they assess.
No new MCP server or hosted CI-esta service is needed.

## Design influences

We use [Moltbook's](https://www.moltbook.com/) simple instruction-URL handoff,
[Stack Overflow for Agents' playbook approach](https://stackoverflow.blog/2026/09/16/here-s-what-s-new-on-stack-overflow-for-agents/)
to bounded, verified procedures, and the open
[Agent Skills](https://agentskills.io/specification) format. Repository-specific
instructions stay in [AGENTS.md](https://agents.md/); detailed adoption commands
load only when needed. These are influences, not affiliations or endorsements.
The skill neither signs up nor posts to external communities.
