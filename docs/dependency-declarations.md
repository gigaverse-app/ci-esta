# Express non-import dependencies in any language

Put dependency declarations next to the code that reads the input. CI-esta uses
pytest-selective's existing format for Bun as well as Python, including its path
patterns, validation and content-versus-import semantics. Do not maintain reader
hashes or invent a second registry for non-Python projects.

For a TypeScript reader, create `src/catalog.ts.gv-dependency.yaml`:

```yaml
dependencies:
  - inputs: ["//fixtures/catalog/*.json"]
    kind: content
    reason: The loader reads catalog data from disk.
```

For several readers in one directory, use `.gv-dependencies.yaml`:

```yaml
dependencies:
  - readers: ["classify.ts", "publish.ts"]
    inputs: ["prompt.md"]
    kind: content
```

Patterns are manifest-relative unless they start with `//`, which anchors them at
the repository root. `relative_to: reader` resolves inputs relative to each reader.
`*`, `?` and whole-segment `**` match tracked files. Use `kind: import` when the reader
executes or imports another module and should inherit its dependencies. Use
`kind: content` when it reads that file's bytes; source code read as text does not
inherit its own imports.

The Bun adapter combines these declarations with Bun's native import graph for
both lane admission and file execution. A changed JSON input selects tests that
reach its reader. A changed declaration selects its readers too. Invalid YAML,
missing owners and unmatched patterns fail visibly rather than becoming a partial
graph that skips work. Removed files and uncertain native graph construction
retain full fallback. Declarations cannot establish test completion or discover
unobserved external state, so retain full checkpoints and execution evidence.

## Start with the audit

From the repository root, after `bun install`:

```bash
ci-esta bun-declarations --root packages --root apps/web
```

Use the roots your test lanes cover (omit `--root` for every tracked test). One run
lists everything at once:

| Section | Meaning | What to do |
| --- | --- | --- |
| Undeclared readers | Reachable modules that name untracked inputs; selection runs the full suite until each is declared | Read each one and declare what it reads or executes |
| Declared readers no test reaches | Their declarations cannot change any selection | Delete them |
| Directories with several sidecars | File sidecars that one manifest can replace | Merge them into `<directory>/.gv-dependencies.yaml` |

It exits 2 while any reader is undeclared and prints *Declarations are complete* when
nothing is left. Run it again before opening the pull request.

Add it to a CI job that has Bun dependencies installed, with `--strict` so declarations
no test reaches and directories of sidecars also fail (exit 1):

```yaml
- name: Dependency declarations are complete and grouped
  run: ci-esta bun-declarations --strict --root packages --root apps/web
```

## Which files need a declaration

The Bun adapter treats a reachable module as uncertain, and runs the full suite,
when its source can name repository inputs the import graph cannot see:

- filesystem reads and inspection: `readFile`, `readdir`, `opendir`, `copyFile`,
  `createReadStream`, `Bun.file`, `Bun.Glob`, `import.meta.glob`, and `stat`,
  `access`, `exists`, `cp`, `glob`, `watch` or `open`, either in their `Sync` form or
  called through an `fs` binding the file creates (`import * as files from "node:fs"`,
  `const { stat } = require("node:fs/promises")`, `{ promises as disk }`);
- computed `import(...)` or `require(...)`, `import.meta.resolve` and `require.resolve`;
- module-relative paths: `new URL("…", import.meta.url)`, `import.meta.dir`,
  `import.meta.dirname`, `__dirname`, and `new Worker("./…")`. These are how a test
  names a sibling script to execute, a worker to start or a fixture to read.

Writing, appending, creating temporary directories and removing files are not
inputs. A module that only does those needs no declaration. Comments are ignored,
so prose such as `// a direct import (not the barrel)` is not a computed import.

Detection reads source text; it cannot see a path built from the working directory,
such as `spawnSync("bash", ["scripts/check.sh"])` or a Bun shell command naming a
repository file. Declare those inputs at the reader yourself.

## Author one manifest per directory

When several readers in one directory need declarations, write one
`.gv-dependencies.yaml` instead of a sidecar per file. Reserve file sidecars for
a lone reader. A directory with five sidecars is a review smell.

```yaml
dependencies:
  - readers: ["report.test.mjs", "upload.test.mjs"]
    inputs: ["{stem}.mjs"]
    kind: import
    reason: Each contract test executes its sibling script in a subprocess.

  - readers: ["report.mjs", "summarize.test.mjs"]
    inputs: []
    reason: Reads only generated reports and temporary fixtures.

  - readers: ["docs-index.test.mjs"]
    inputs: ["//scripts/generate-docs-index.ts"]
    kind: import
    reason: Copies and executes the index generator.
```

- **`kind` follows what the reader does with the file.** Executing it (a
  subprocess, `spawn`, `Bun.spawn`, `execFile`, dynamic import) is `kind: import`,
  so changes to what the script imports select the reader. Reading its bytes is
  `kind: content`. A test that runs a sibling script declared as `content`
  misses regressions in that script's imports.
- **`{stem}`** is the reader's file name before its first dot: `report.test.mjs`
  pairs with `report.mjs`. Every matched reader must have its sibling.
- **`inputs: []`** records a reader reviewed as having no repository inputs. It
  requires `reason`. Check the reader first: if it reads any tracked file, declare
  that file instead.
- **Explain with `reason`**, not YAML comments. Never copy the same comment across
  files.
- **Keep inputs as narrow as the reader.** `//**/*.md` or a whole application tree
  is correct only when the reader really scans all of it; otherwise name the
  directory or files it reads.

`{stem}` and `inputs: []` need `selective-deps` 1.8.0 or later. With older
releases, a file sidecar containing `dependencies: []` records the same review.

## Migrate from a reviewedReaders policy

The deprecated `policy` input of `run-bun-tests` scans every tracked file under
`runtimeRoots`, pins each reviewed reader to its Git blob, and runs the full suite
whenever any reviewed input changes. Every edit to a reader means a new hash, and a
detection change upstream can flag files no test even imports. Declarations cover
only readers a test reaches, carry no hashes, and select just the tests that reach a
changed input.

1. Remove the `policy` input, and any step that writes a per-lane policy file.
2. Run `ci-esta bun-declarations --root …` with each lane's test roots. Declare only
   the readers it lists. A reviewed reader that no test reaches needs nothing.
3. Carry each listed reader's reviewed `inputs` into a manifest, minus:
   - environment files (`package.json`, `bun.lock`, `bunfig*.toml`, `tsconfig*.json`),
     which already run the full suite when they change;
   - inputs that affect every test, such as `patches/`. Undeclared, a change to them
     runs the full suite; declared, it would select only this reader's tests.
   An entry with `"inputs": []` becomes `inputs: []` with a `reason`.
4. Drop `scopedRoots`, `runtimeRoots`, `unaffectedPaths` and `unaffectedRoots`. The
   import graph decides scope; Markdown that no reader declares selects no tests, and
   any other unmodeled file still runs the full suite.
5. Replace hand-written reader checks and hash-refresh scripts with the
   `ci-esta bun-declarations --strict` CI step above.

For another language adapter, install only `selective-deps` and
call its `dependency_edges(manifests, files, revision=...)` API. It consumes manifest
bytes and tracked paths supplied by the adapter; it does not install pytest, load
the Python selector, inspect imports, open caches or call Git. The parser is the
same implementation the full Python selector uses. Combine the returned edges
with the language's native graph, preserving content nodes as leaves.

See the [portable API](https://github.com/gigaverse-app/pytest-selective/tree/main/declarations)
and [Bun execution recipe](bun-test-selection.md).
