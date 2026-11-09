// Bun's import edges for the entry points in the JSON file argv[2] (`{"entries": [...], "files": [...]}`,
// `files` being the repository's tracked files), written as JSON to argv[3].
//
// `packages: "external"` keeps the build independent of node_modules. Every import that names a
// repository file by more than a relative path is resolved here with Bun's resolver and recorded,
// with its specifier, as `resolved` edges to absolute paths, because the metafile alone hides it:
// - A query-suffixed import (`./icon.svg?react`, `@/style.css?raw`): Bun's runtime loads the file
//   without its query, but the bundler fails on a relative one and externalizes an aliased one.
// - A tsconfig `paths` alias Bun tree-shakes away stays external under its specifier, and Bun 1.3
//   names an alias import of a module it has already parsed by its specifier alone.
// - A workspace package, or a local `file:`/`link:`/`./path` dependency, imported by name
//   (`@scope/lib/util`): the runtime reaches it through a node_modules link, so without
//   node_modules it is external. Resolution falls back to its directory, ignoring `exports` maps.
// - An import of a file that exists only with a tsconfig `moduleSuffixes` suffix, as React Native
//   platform files do (`./Button` naming `Button.ios.tsx` and `Button.android.tsx`): Bun's
//   resolver ignores `moduleSuffixes`, so it fails. Every suffixed variant, and the unsuffixed
//   file if there is one, is an edge.
// A relative import that reaches into node_modules (`../../node_modules/pkg/file.js`) names a
// package file, like a bare package import, so it stays external whether or not packages are installed.
import { existsSync, realpathSync, statSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, sep } from "node:path";

const [request, output] = process.argv.slice(2);
const { entries, files }: { entries: string[]; files: string[] } = await Bun.file(request).json();
const root = realpathSync(process.cwd());
const manifest = await Bun.file("package.json")
  .json()
  .catch(() => ({}));

/** Package name -> directory, for workspaces and local dependencies a node_modules link would reach. */
const local = new Map<string, string>();
const patterns: string[] = (Array.isArray(manifest.workspaces) ? manifest.workspaces : manifest.workspaces?.packages) ?? [];
for (const pattern of patterns) {
  for (const found of new Bun.Glob(`${pattern}/package.json`).scanSync({ onlyFiles: true })) {
    const { name } = await Bun.file(found).json();
    if (name) local.set(name, join(root, dirname(found)));
  }
}
for (const field of ["dependencies", "devDependencies", "optionalDependencies", "peerDependencies"]) {
  for (const [name, version] of Object.entries<string>(manifest[field] ?? {})) {
    // `file:` and `link:` take any path; a bare version must start with `./` or `../` to be a path.
    const path = /^(?:file|link):(.+)$/.exec(version)?.[1] ?? (/^\.\.?\//.test(version) ? version : undefined);
    const directory = path === undefined ? undefined : join(root, path);
    if (directory && existsSync(directory) && statSync(directory).isDirectory()) local.set(name, directory);
  }
}

// TypeScript's `moduleSuffixes`, from the root tsconfig.json alone: an `extends` chain may live in
// node_modules, which the planner does not need.
const tsconfig = await Bun.file("tsconfig.json")
  .text()
  .then((text) => Bun.JSONC.parse(text))
  .catch(() => ({}));
const suffixes: string[] = (tsconfig?.compilerOptions?.moduleSuffixes ?? []).filter((suffix: string) => suffix);
const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const SUFFIXED = new RegExp(`^(.*)(?:${suffixes.map(escape).join("|")})\\.[cm]?[jt]sx?$`);
/** Import specifiers' last segments that may name a suffixed file: its stem, and its directory for an index. */
const stems = new Set<string>();
for (const file of suffixes.length ? files : []) {
  const stem = SUFFIXED.exec(basename(file))?.[1];
  if (stem === undefined) continue;
  stems.add(stem);
  if (stem === "index") stems.add(basename(dirname(file)));
}

/** The repository file `specifier` names from `directory`, or undefined for a package or no file. */
function repositoryFile(specifier: string, directory: string): string | undefined {
  const name = specifier.startsWith("@") ? specifier.split("/", 2).join("/") : specifier.split("/")[0];
  const owner = local.get(name);
  for (const [request, from] of [
    [specifier, directory],
    ...(owner ? [[join(owner, specifier.slice(name.length)), root]] : []),
  ]) {
    try {
      const file = realpathSync(Bun.resolveSync(request, from));
      const path = relative(root, file);
      return path.startsWith("..") || isAbsolute(path) || path.split(sep).includes("node_modules") ? undefined : file;
    } catch {
      // Try the package's directory next.
    }
  }
  return undefined;
}

/** Each `moduleSuffixes` variant of `specifier` that is a repository file, as TypeScript resolves them. */
function suffixedFiles(specifier: string, directory: string): string[] {
  return suffixes
    .flatMap((suffix) => [specifier + suffix, `${specifier}/index${suffix}`])
    .map((candidate) => repositoryFile(candidate, directory))
    .filter((file): file is string => file !== undefined);
}

/** The repository files `specifier` names: the file Bun resolves and every suffixed variant. */
function repositoryFiles(specifier: string, directory: string): string[] {
  const file = repositoryFile(specifier, directory);
  return [...new Set([...(file ? [file] : []), ...suffixedFiles(specifier, directory)])];
}

const resolved: Record<string, { path: string; kind: string; original: string }[]> = {};
const recorded = new Set<string>();
function record(importer: string, specifier: string, kind: string): void {
  const key = JSON.stringify([importer, specifier]);
  if (recorded.has(key)) return;
  recorded.add(key);
  const query = specifier.indexOf("?");
  for (const file of repositoryFiles(query < 0 ? specifier : specifier.slice(0, query), dirname(importer))) {
    (resolved[importer] ??= []).push({ path: file, kind, original: specifier });
  }
}

const plugins: Bun.BunPlugin[] = [
  {
    name: "node-modules-paths",
    setup(build) {
      build.onResolve({ filter: /^\.\.?\/(?:.*\/)?node_modules\// }, ({ path }) => ({ path, external: true }));
    },
  },
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
];
if (stems.size) {
  plugins.push({
    name: "module-suffixes",
    setup(build) {
      // Only specifiers whose last segment is the stem of a suffixed file reach JavaScript.
      const filter = new RegExp(`(?:^|/)(?:${[...stems].map(escape).join("|")})$`);
      build.onResolve({ filter }, ({ path, importer, kind }) => {
        if (!importer || !suffixedFiles(path, dirname(importer)).length) return undefined;
        record(importer, path, kind);
        return { path, external: true };
      });
    },
  });
}

const result = await Bun.build({
  entrypoints: entries.map((entry) => `./${entry}`),
  target: "bun",
  packages: "external",
  root: ".",
  metafile: true,
  // Entry points that differ only in extension (`x.test.ts`, `x.test.tsx`) share `[dir]/[name]`.
  naming: "[dir]/[name]-[hash].[ext]",
  throw: false,
  plugins,
});
if (!result.success || !result.metafile) {
  // Errors first: a warning, such as Bun's own about `moduleSuffixes`, is not why the build failed.
  const logs = [...result.logs].sort((a, b) => Number(b.level === "error") - Number(a.level === "error"));
  for (const log of logs) {
    const file = log.position && relative(root, log.position.file).split(sep).join("/");
    const where = log.position ? ` (${file}:${log.position.line})` : "";
    console.error(`${log.level}: ${log.message}${where}`);
  }
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
