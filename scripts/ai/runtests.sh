#!/usr/bin/env bash
# Compatibility wrapper: exec scripts/ai/run_tests.sh
# Kept for backward compatibility with camelCase references.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/run_tests.sh" "$@"
