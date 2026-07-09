#!/usr/bin/env bash
# Compatibility wrapper: exec scripts/ai/make_delivery_summary.sh
# Kept for backward compatibility with camelCase references.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/make_delivery_summary.sh" "$@"
