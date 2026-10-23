# Shared public action directory

Use only `actions/NAME` entry points. Migrate root, named and `.github/actions/NAME`
callers to the canonical path; older immutable releases retain their original layout.

- [x] Verify action input/default/output contracts and reject duplicate entry points.
- [x] Route changes to action metadata and helper files to the full test lane.
- [x] Include the shared directory in execution evidence and distribution inputs.
- [x] Validate updated workflows and examples with actionlint.
- [ ] Run hosted smoke tests through the new directory and pass normal CI.
