#!/usr/bin/env bash
# Compatibility wrapper: exec scripts/ai/codex_dev.sh
# Kept for backward compatibility with camelCase references.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/codex_dev.sh" "$@"
