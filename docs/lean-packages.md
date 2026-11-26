# Prehydrated Lean packages on ephemeral Linux runners

A runner image can keep Mathlib's compiled artifacts across jobs even when each job starts with an empty home. `restore-lean-packages` copies the dependency checkouts and their build outputs into the job's own `.lake/packages`. The project build and its proof checks still run. Only a successful copy replaces the project's usual dependency hydration step.

## Prepare a seed

Use an unprivileged image-builder account and a clean checkout of a trusted revision on the same Linux runner image and architecture. Install the pinned toolchain and hydrate the dependencies exactly as CI would, for example:

```sh
lake exe mathlib/cache get
```

Make the resulting checkout available to runner jobs at a read-only path such as `/opt/lean-seeds/current`. Its Git packages must be standalone clones without credentials or references to private directories. Make the files readable by the runner, preserving the normal owner write bits for the job's private copy. Publish a new immutable directory and atomically switch `current` after hydration succeeds. Keep the old directory while jobs using it finish. Never populate this directory from a pull request.

Place the seed and workspace on the same reflink-capable filesystem (for example, Btrfs or XFS with reflink enabled) for copy-on-write copies. On other filesystems GNU `cp` copies the bytes. Measure the copy time and allow sufficient disk space before using that configuration.

To reuse the compiler as well, provision the seed's own `.elan/toolchains` with Elan for the pinned Lean release. Set `link-elan-toolchains: 'true'` and run the action before your ordinary Elan setup. CI-esta links each installed toolchain into a fresh, private Elan registry. Elan selects the requested version and installs any missing version normally. Existing job registries are left alone.

## Use the seed

```yaml
- uses: gigaverse-app/ci-esta/actions/restore-lean-packages@v1
  id: lean-packages
  with:
    seed-directory: /opt/lean-seeds/current
- if: steps.lean-packages.outputs.cache-hit != 'true'
  run: lake exe mathlib/cache get
- run: lake build
```

The action compares `lean-toolchain`, `lakefile.toml` and `lake-manifest.json` byte for byte. It supports pinned Lean releases (including release candidates), Git dependencies at full revisions and the standard Lake package layout. Missing seeds, changed inputs and pre-existing workspace packages take the regular hydration path. An interrupted copy is discarded before the fallback runs. Repository build products, axiom checks and project-specific validation belong to the consuming workflow.

A hit trusts the runner image in the same way as an installed compiler. Provisioning and disk are costs of that image. For a benchmark, report the one-time preparation time, the per-job copy time, and checkout-to-verdict time on the same Lean change, including compilation and proof checks.
