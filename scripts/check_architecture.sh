#!/usr/bin/env bash
# make arch-check: fail when docs/architecture.md no longer names every compose service,
# layer adapter type and project. It catches missing names, not wrong arrows: keep the diagrams honest by hand.
set -uo pipefail
cd "$(dirname "$0")/.."

doc=docs/architecture.md
missing=()

# Service names: two-space-indented keys inside the top-level `services:` block.
services=$(awk '/^[a-z]/ { in_s = ($0 ~ /^services:/) } in_s && /^  [a-z0-9_-]+:$/ { sub(/:$/, ""); print $1 }' compose.yaml)
adapters=$(sed -n '/^const registry/,/^};/p' frontend/src/lib/adapters.ts | grep -oE "^\s+'[a-z-]+'" | tr -d " '\t")
projects=$(grep -oE '"[a-z0-9-]+"' projects/index.json | tr -d '"' | grep -v '^projects$')

for name in $services $adapters $projects; do
  grep -qF -- "$name" "$doc" || missing+=("$name")
done

if (( ${#missing[@]} )); then
  echo "FAIL  $doc is missing: ${missing[*]}"
  exit 1
fi
echo "PASS  $doc names all $(wc -w <<<"$services $adapters $projects") services, adapters and projects"
