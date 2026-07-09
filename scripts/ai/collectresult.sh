#!/usr/bin/env bash
# Compatibility wrapper: exec scripts/ai/collect_result.sh
# Kept for backward compatibility with camelCase references.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/collect_result.sh" "$@"
