// Bun's import edges for the entry points listed in the JSON file argv[2], written as JSON to argv[3].
//
// `packages: "external"` keeps the build independent of node_modules. Every import that names a
// repository file by more than a relative path is resolved here with Bun's resolver and recorded,
// with its specifier, as a `resolved` edge to an absolute path, because the metafile alone hides it:
// - A query-suffixed import (`./icon.svg?react`, `@/style.css?raw`): Bun's runtime loads the file
//   without its query, but the bundler fails on a relative one and externalizes an aliased one.
// - A tsconfig `paths` alias Bun tree-shakes away stays external under its specifier, and Bun 1.3
//   names an alias import of a module it has already parsed by its specifier alone.
// - A workspace package imported by name (`@scope/lib/util`): the runtime reaches it through a
//   node_modules link, so without node_modules it is external. Resolution falls back to the
//   workspace directory, ignoring `exports` maps.
import { realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, sep } from "node:path";

const [entries, output] = process.argv.slice(2);
const root = realpathSync(process.cwd());
const manifest = await Bun.file("package.json")
  .json()
  .catch(() => ({}));
const patterns: string[] = (Array.isArray(manifest.workspaces) ? manifest.workspaces : manifest.workspaces?.packages) ?? [];
const workspaces = new Map<string, string>();
for (const pattern of patterns) {
  for (const found of new Bun.Glob(`${pattern}/package.json`).scanSync({ onlyFiles: true })) {
    const { name } = await Bun.file(found).json();
    if (name) workspaces.set(name, join(root, dirname(found)));
  }
}

/** The repository file `specifier` names from `directory`, or undefined for a package or no file. */
function repositoryFile(specifier: string, directory: string): string | undefined {
  const name = specifier.startsWith("@") ? specifier.split("/", 2).join("/") : specifier.split("/")[0];
  const workspace = workspaces.get(name);
  for (const [request, from] of [
    [specifier, directory],
    ...(workspace ? [[join(workspace, specifier.slice(name.length)), root]] : []),
  ]) {
    try {
      const file = realpathSync(Bun.resolveSync(request, from));
      const path = relative(root, file);
      return path.startsWith("..") || isAbsolute(path) || path.split(sep).includes("node_modules") ? undefined : file;
    } catch {
      // Try the workspace directory next.
    }
  }
  return undefined;
}

const resolved: Record<string, { path: string; kind: string; original: string }[]> = {};
const recorded = new Set<string>();
function record(importer: string, specifier: string, kind: string): void {
  const key = JSON.stringify([importer, specifier]);
  if (recorded.has(key)) return;
  recorded.add(key);
  const query = specifier.indexOf("?");
  const file = repositoryFile(query < 0 ? specifier : specifier.slice(0, query), dirname(importer));
  if (file) (resolved[importer] ??= []).push({ path: file, kind, original: specifier });
}

const result = await Bun.build({
  entrypoints: (await Bun.file(entries).json()).map((entry: string) => `./${entry}`),
  target: "bun",
  packages: "external",
  root: ".",
  metafile: true,
  throw: false,
  plugins: [
    {
      name: "query-imports",
      setup(build) {
        // A query import stays external; a missing relative one then fails in the planner.
        build.onResolve({ filter: /\?/ }, ({ path, importer, kind }) => {
          record(importer, path, kind);
          return { path, external: true };
        });
      },
    },
  ],
});
if (!result.success || !result.metafile) {
  for (const log of result.logs) console.error(String(log));
  process.exit(1);
}
// Imports Bun parsed no file for, tree-shaken ones included, except relative and absolute paths
// and `bun:`/`node:` built-ins.
const named = /^(?![./]|[a-zA-Z]+:)/;
for (const [importer, input] of Object.entries(result.metafile.inputs)) {
  for (const { path, kind } of input.imports) {
    if (named.test(path) && !(path in result.metafile.inputs)) record(join(root, importer), path, kind);
  }
}
await Bun.write(output, JSON.stringify({ inputs: result.metafile.inputs, resolved }));
