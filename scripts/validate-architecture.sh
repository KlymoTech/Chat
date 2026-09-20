#!/usr/bin/env bash
set -Eeuo pipefail

required_paths=(
  "frontend/package.json"
  "frontend/Dockerfile"
  "backend/pyproject.toml"
  "backend/Dockerfile"
  "backend/src/northstar_api"
  "backend/src/northstar_api/modules/knowledge"
  "backend/migrations"
  "database/postgres"
  "docker/README.md"
  "infrastructure/redis/README.md"
  "infrastructure/rabbitmq/README.md"
  "infrastructure/kafka/README.md"
  "infrastructure/minio/README.md"
  "kubernetes/base/kustomization.yaml"
  "kubernetes/overlays/production/kustomization.yaml"
  "compose.yaml"
  "frontend/src/features/knowledge/index.ts"
)

for path in "${required_paths[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "Architecture contract violation: required path is missing: $path" >&2
    exit 1
  fi
done

# New production consumers use the feature-owned knowledge boundary. The three
# legacy implementation files remain callable only as compatibility adapters.
violations="$(
  grep -R -n -E 'northstar_api\.services\.(ingestion|retrieval|grounding)' \
    backend/src/northstar_api --include='*.py' \
    | grep -v -E '/services/(ingestion|retrieval|grounding)\.py:|/modules/knowledge/' \
    || true
)"
if [[ -n "$violations" ]]; then
  echo "$violations"
  echo "Architecture contract violation: production code bypasses modules/knowledge." >&2
  exit 1
fi

# These obsolete umbrella roots duplicate canonical application and
# infrastructure boundaries and previously produced confusing empty folders.
legacy_roots=(apps deploy infra services)
for path in "${legacy_roots[@]}"; do
  if [[ -e "$path" ]]; then
    echo "Architecture contract violation: obsolete root exists: $path" >&2
    echo "Use frontend/, backend/, kubernetes/, or infrastructure/ instead." >&2
    exit 1
  fi
done

echo "Repository architecture contract passed."
