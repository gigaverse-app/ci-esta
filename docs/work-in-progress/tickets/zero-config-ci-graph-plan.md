# Zero-configuration work selection through one CI graph

Retire when the phases below have shipped and the gigaverse-app adopters plan their
lanes with no path globs for workflows, CI scripts, environment or package files.

## Goal

Adopting CI-esta should be the whole adoption. A repository adds the planner and the
gate, and the defaults decide what runs. Configuration stays optional, for
repositories with non-standard layouts that want extra speed.

On 2026-11-08 every gigaverse-app adopter needed hand-written lane files, and most
still ran tests, builds or whole matrices on documentation-only pull requests. The
cause was path rules standing in for knowledge CI-esta can derive:

- workflows and `.github/` files counted as global inputs;
- `ci.yml#job` inputs were declared by hand;
- lane inputs were file-type lists;
- build and smoke jobs had no lane at all.

## Ownership

CI-esta owns what is true for every language: the workflow graph, composing lanes and
jobs, rules, non-test targets, and the gate. Each language's runner owns which tests a
change affects, including that language's environment files:

| Runner | Selector | Environment it interprets |
| --- | --- | --- |
| pytest | [pytest-selective](https://github.com/gigaverse-app/pytest-selective) | `uv.lock`, `poetry.lock`, `requirements*`, `pyproject.toml` |
| bun test | Bun's `--changed`, through [the Bun adapter](../../bun-test-selection.md) | `bun.lock`, `package.json` |

A Bun repository adopting CI-esta gets the same workflow graph, lane composition and
defaults as a Python one. Only the selector differs.

## Model

```text
changed files ─┬─► language selector ──► affected tests (+ package inputs touched)
               └─► workflow graph ─────► changed jobs, and files those jobs execute
                                                   │
                         composition: tests → lanes by roots; jobs → the lanes they gate;
                         targets (package build, smokes) → their jobs; rules
                                                   ▼
                                lanes and jobs to run ──► validation gate
```

**The workflow graph.** Every job is a node:
- **Lanes:** a job runs the lanes its conditions read (`fromJSON(needs.PLANNER.outputs.lanes).LANE`). The planner job runs every lane.
- **Inputs:** a job depends on the repository files it executes: paths named in `run`, `with` and local `uses` values, followed into composite, JavaScript and Docker actions and reusable workflows.
- **Selection:**
  - a changed job selects its lanes;
  - a changed file selects the lanes of every job that executes it;
  - a change outside `jobs:` selects every lane the workflow runs;
  - a `.github/` file no job executes, such as a pull-request template, selects nothing.

This replaces the hand-declared `ci.yml#job` inputs. It also unifies the two lane
parsers CI-esta has today: `workflow_inputs.py` (job projections) and
`check-workflow`'s lane mapping.

**Zero-configuration lanes.** The lanes are the names the workflow's conditions read.
A lane's test roots come from the test commands its jobs run, such as `pytest tests/unit`
or `bun test packages/app`. When a command names no root, the lane takes every test, and
the plan says so. A lane file is needed only to override these defaults.

**Targets.** A job that builds or installs the package selects when the package
inputs change. The selector reports those inputs: for Python, the package sources and
the `readme` and `license-files` that `pyproject.toml` embeds; for Bun, `package.json`
`files` and entry points.

**Rules** are the one customization syntax. They are graph edges, with named built-in
defaults that can be inspected and overridden:
`{"when": [...], "select": ["lane:NAME" | "job:PATH#ID" | "all"], "reason": "..."}`.

## Phases

Each phase ships within `v1`, keeps today's lane files valid, and adds real-Git
routing tests, including a documentation-only probe.

- [ ] **1. Workflow graph.** Jobs, the lanes they gate, and the files and actions they
      execute. A planner action composes pytest-selective's lane plan with it, and the
      `ci.yml#job` inputs become unnecessary. One lane-reference parser serves
      `check-workflow`, `workflow_inputs.py` and the planner.
- [ ] **2. Bun parity.** The Bun adapter's affected tests feed the same composition.
- [ ] **3. Targets.** Package build and smoke jobs from the selectors' package inputs.
- [ ] **4. Zero-configuration lanes.** Lanes and roots inferred from the workflow; the
      lane file becomes optional.
- [ ] **5. Rules.** One syntax with named defaults; existing lane `inputs` and
      `global_inputs` read as rules.
- [ ] **6. Adopters.** Remove the hand-written lane inputs from the gigaverse-app
      repositories, and the documentation-only audit's workarounds from the guides.
