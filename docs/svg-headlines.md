# SVG headlines with private attachments

The opt-in `headline-svg: true` input renders the same Python and Bun figures
as passive SVG metric strips. Native `<details>` sections retain the original
tables, evidence links, and copyable values. Dark and light images share one
layout. Selection, execution, reuse and missing evidence keep their meanings.

GitHub removes inline `<svg>` from comments. The reporter uses the attachment
endpoint used by GitHub CLI v2.102.0 instead. It uploads only to the repository
in the report provenance and verifies its numeric repository ID and visibility.
For private repositories, a harmless probe must return an anonymous 401, 403 or
404 before any metric image is uploaded. Unknown visibility, redirects, upload
failure, or unsupported credentials keep the complete text report. This mode
never sends metric values to Shields, a public asset repository, a gist, Pages,
or an external image renderer. The static CI-esta banner contains no run data.

## Credentials and rollout

GitHub's attachment endpoint currently accepts OAuth/user tokens and personal
access tokens with write access to the target repository. It does **not** accept
the ordinary Actions installation token. The optional `headline-asset-token`
action input (or identically named reusable-workflow secret) supplies an existing,
repository-authorized user credential. If omitted, the action tries its existing
`github-token`; unsupported tokens retain text headlines. Do not enlarge token
permissions or provision a credential merely to make a preview look right.

The option defaults to false. This change does not configure consumer secrets,
change repository visibility, alter validation, or grant permissions. Job
summaries remain text; the sticky and its Markdown artifact use uploaded images
when available. Existing publication ownership, freshness, and serialization
still apply. Disable `headline-svg` to return to the existing presentation.

Each update creates immutable attachments, so old image caches cannot show new
figures under old URLs. Attachments are retained by GitHub; this version does not
delete old uploads. A failed batch may leave unused private attachments. Image
bytes are generated locally with no scripts, external resources or embedded
fonts. Plain text remains inside expanded sections and in image alt text.

## Verify in GitHub before release

Use recorded JSON from the same private repository and publish through the normal
sticky client under a separate, explicitly labelled preview key. Never copy a
private report or screenshot into the public toolkit repository. Inspect actual
GitHub rendering, open and close the details, check both provider layouts, and
verify anonymous denial for every metric attachment. A local HTML mockup is not
acceptance evidence. Preview publication with a user token demonstrates the image
path; it does not demonstrate that an unconfigured Actions token can upload.

References: [GitHub attachment access](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files),
[CLI uploader authentication and repository binding](https://github.com/cli/cli/blob/v2.102.0/internal/attachments/client.go).
