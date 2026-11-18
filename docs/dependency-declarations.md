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

## Which files need a declaration

The Bun adapter treats a reachable module as uncertain, and runs the full suite,
when its source can name repository inputs the import graph cannot see:

- filesystem reads and inspection: `readFile`, `readdir`, `stat`, `exists`,
  `access`, `copyFile`, `cp`, `glob`, `createReadStream`, `Bun.file`, `Bun.Glob`,
  `import.meta.glob`;
- computed `import(...)` or `require(...)`;
- module-relative paths: `new URL("./…", import.meta.url)`, `import.meta.dir`,
  `import.meta.dirname`, `__dirname`. These are how a test names a sibling script
  to execute or a fixture to read.

Writing, appending, creating temporary directories and removing files are not
inputs. A module that only does those needs no declaration.

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

For another language adapter, install only `selective-deps` and
call its `dependency_edges(manifests, files, revision=...)` API. It consumes manifest
bytes and tracked paths supplied by the adapter; it does not install pytest, load
the Python selector, inspect imports, open caches or call Git. The parser is the
same implementation the full Python selector uses. Combine the returned edges
with the language's native graph, preserving content nodes as leaves.

See the [portable API](https://github.com/gigaverse-app/pytest-selective/tree/main/declarations)
and [Bun execution recipe](bun-test-selection.md).
