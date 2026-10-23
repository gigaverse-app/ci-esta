#!/usr/bin/env bash
# Re-tag an immutable ECR manifest inside one repository.
#
# Required environment:
#   SOURCE_IMAGE_TAG  full ECR source ref for a previously verified artifact
#   TARGET_IMAGE_TAG  full ECR target ref consumed by deployment
#
# Registry errors, missing images, conflicts, and digest mismatches all emit
# reused=false and exit successfully so the caller can run its ordinary build.
set -uo pipefail

: "${SOURCE_IMAGE_TAG:?SOURCE_IMAGE_TAG is required}"
: "${TARGET_IMAGE_TAG:?TARGET_IMAGE_TAG is required}"

reused=false
reason="unresolved"
digest=
source_digest=

write_outputs() {
  if [ -z "${GITHUB_OUTPUT:-}" ]; then
    return
  fi
  {
    printf 'reused=%s\n' "$reused"
    printf 'reason=%s\n' "$reason"
    printf 'digest=%s\n' "$digest"
    printf 'source-digest=%s\n' "$source_digest"
  } >> "$GITHUB_OUTPUT"
}
trap write_outputs EXIT

parse_ecr_ref() {
  local ref="$1"
  local registry="${ref%%/*}"
  local repository_and_tag="${ref#*/}"

  if [[ "$registry" != *.dkr.ecr.*.amazonaws.com ]] ||
    [[ "$repository_and_tag" != *:* ]] ||
    [[ "$repository_and_tag" == *@* ]]; then
    return 1
  fi

  PARSED_REGISTRY="$registry"
  PARSED_REPOSITORY="${repository_and_tag%:*}"
  PARSED_TAG="${repository_and_tag##*:}"
  [ -n "$PARSED_REPOSITORY" ] && [ -n "$PARSED_TAG" ]
}

if ! parse_ecr_ref "$SOURCE_IMAGE_TAG"; then
  reason="invalid-source-ref"
  echo "::warning::Cannot reuse malformed source ECR ref: $SOURCE_IMAGE_TAG"
  exit 0
fi
source_registry="$PARSED_REGISTRY"
source_repository="$PARSED_REPOSITORY"
source_tag="$PARSED_TAG"

if ! parse_ecr_ref "$TARGET_IMAGE_TAG"; then
  reason="invalid-target-ref"
  echo "::warning::Cannot reuse malformed target ECR ref: $TARGET_IMAGE_TAG"
  exit 0
fi
target_registry="$PARSED_REGISTRY"
target_repository="$PARSED_REPOSITORY"
target_tag="$PARSED_TAG"

if [ "$source_registry/$source_repository" != "$target_registry/$target_repository" ]; then
  reason="repository-mismatch"
  echo "::warning::Source and target ECR repositories differ; building instead"
  exit 0
fi

lookup_manifest() {
  aws ecr batch-get-image \
    --repository-name "$source_repository" \
    --image-ids "imageTag=$1" \
    --accepted-media-types \
    application/vnd.oci.image.index.v1+json \
    application/vnd.docker.distribution.manifest.list.v2+json \
    application/vnd.oci.image.manifest.v1+json \
    application/vnd.docker.distribution.manifest.v2+json \
    --output json
}

if ! source_response=$(lookup_manifest "$source_tag" 2>/dev/null); then
  reason="source-lookup-failed"
  echo "::warning::ECR lookup failed for $SOURCE_IMAGE_TAG; building instead"
  exit 0
fi
if ! source_manifest=$(jq -r '.images[0].imageManifest // empty' <<< "$source_response") ||
  ! source_media_type=$(jq -r '.images[0].imageManifestMediaType // empty' <<< "$source_response") ||
  ! source_digest=$(jq -r '.images[0].imageId.imageDigest // empty' <<< "$source_response"); then
  reason="source-response-invalid"
  source_digest=
  echo "::warning::ECR returned an invalid source response; building instead"
  exit 0
fi
if [ -z "$source_manifest" ] || [ -z "$source_digest" ]; then
  reason="source-missing"
  source_digest=
  echo "No reusable source image at $SOURCE_IMAGE_TAG; building instead"
  exit 0
fi

if ! target_response=$(lookup_manifest "$target_tag" 2>/dev/null); then
  reason="target-lookup-failed"
  echo "::warning::ECR lookup failed for $TARGET_IMAGE_TAG; building instead"
  exit 0
fi
if ! target_digest=$(jq -r '.images[0].imageId.imageDigest // empty' <<< "$target_response"); then
  reason="target-response-invalid"
  echo "::warning::ECR returned an invalid target response; building instead"
  exit 0
fi
if [ -n "$target_digest" ]; then
  if [ "$target_digest" = "$source_digest" ]; then
    reused=true
    reason="target-exists"
    digest="$target_digest"
    echo "Exact deployment image already exists: $TARGET_IMAGE_TAG ($target_digest)"
  else
    reason="target-conflict"
    echo "::warning::Target tag resolves to a different digest; building instead"
  fi
  exit 0
fi

put_args=(
  --repository-name "$source_repository"
  --image-tag "$target_tag"
  --image-manifest "$source_manifest"
)
if [ -n "$source_media_type" ]; then
  put_args+=(--image-manifest-media-type "$source_media_type")
fi

if ! promoted_digest=$(
  aws ecr put-image "${put_args[@]}" \
    --query 'image.imageId.imageDigest' \
    --output text 2>/dev/null
); then
  reason="promotion-failed"
  echo "::warning::ECR promotion failed for $SOURCE_IMAGE_TAG; building instead"
  exit 0
fi

if [ "$promoted_digest" != "$source_digest" ]; then
  reason="digest-mismatch"
  echo "::warning::Promoted digest differs from the verified source; building instead"
  exit 0
fi

reused=true
reason="promoted"
digest="$promoted_digest"
echo "Reused exact ECR image: $SOURCE_IMAGE_TAG -> $TARGET_IMAGE_TAG ($promoted_digest)"
