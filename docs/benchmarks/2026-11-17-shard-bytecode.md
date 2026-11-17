# Bytecode before parallel test shards, 2026-11-17

uv installs packages without compiled bytecode, so the first Python process to
import a module compiles it. A job that then starts sixteen test shards has
sixteen processes compiling the same modules at the same moment. Compiling once
during the install cut gigaverse-ai's cold collection from a median of 43 s to
26 s, for about 3 s of extra setup.

## What was slow

In full gigaverse-ai runs each of 16 pytest shards spent 48-89 s outside its
test cases. One shard's phases on a fresh environment, from process start
(one process of sixteen, `--collect-only`, about 100 test files):

| Phase | No bytecode | Bytecode in place |
| --- | ---: | ---: |
| pytest configured (plugins and conftests imported) | 18-27 s | 10-13 s |
| Collection finished | 28-38 s | 17-23 s |
| Process exited | 30-40 s | 18-25 s |

pytest-selective's plugins are not the cost: collecting the same 101 files took
17.1-17.5 s with no extra plugin, with `-p selective`, and with the read audit.

## Controlled comparison

[Run 44149991084](https://github.com/gigaverse-app/gigaverse-ai/actions/runs/44149991084),
three fresh `arc-linux-16` pods per variant, all on 32-CPU Intel nodes. Each job
installs the locked environment, then starts 16 `pytest --collect-only`
processes at once, one per CPU, covering the whole test tree between them.

- **Plain:** `setup-cached-uv` as released.
- **Compiled:** `UV_COMPILE_BYTECODE=1` during the sync, then
  `python -m compileall -q -j 0 src tests tools`.

| Per job | Plain | Compiled |
| --- | --- | --- |
| Setup (install, plus compile) | 7.9, 9.3, 9.9 s | 11.0, 11.5, 14.0 s |
| Sixteen cold shards collect | 39.3, 43.1, 48.5 s | 22.6, 25.6, 29.9 s |
| Setup plus shards | 48.7, 51.0, 58.6 s | 34.2, 36.6, 44.0 s |

uv compiled 30,622 files in 2.7-3.7 s; the first-party compile took about 1 s.
The median job was 14 s shorter with bytecode.

## Limits

- Three jobs per variant, collection only. Real shards also run tests, and
  imports first reached during a test are not in these numbers.
- One repository and one runner type. A job that starts one Python process
  gains little: that process compiles each module once either way.
- With `cache-environment: 'true'` the compiled files are saved in the cached
  environment, which makes that archive larger. Not measured.
