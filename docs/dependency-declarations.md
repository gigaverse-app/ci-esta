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

A reachable filesystem reader or computed import without a declaration makes
the graph uncertain and runs the full suite. Declare its actual inputs to enable
selection. For code that only writes output, or dynamically loads external
packages already covered by the lockfile, a file sidecar containing
`dependencies: []` records that review without inventing repository inputs.
Use this only after checking the reader; it is not a blanket exemption.

For another language adapter, install only `selective-deps` and
call its `dependency_edges(manifests, files, revision=...)` API. It consumes manifest
bytes and tracked paths supplied by the adapter; it does not install pytest, load
the Python selector, inspect imports, open caches or call Git. The parser is the
same implementation the full Python selector uses. Combine the returned edges
with the language's native graph, preserving content nodes as leaves.

See the [portable API](https://github.com/gigaverse-app/pytest-selective/tree/main/declarations)
and [Bun execution recipe](bun-test-selection.md).
