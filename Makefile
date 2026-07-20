.PHONY: engineering-preflight engineering-test engineering-secrets engineering-ci

# Local default: ordinary preflight (branch warn on main, dirty warn).
# CI: make engineering-preflight ENGINEERING_PREFLIGHT_ARGS=--ci
ENGINEERING_PREFLIGHT_ARGS ?=

engineering-preflight:
	bash scripts/engineering/preflight.sh $(ENGINEERING_PREFLIGHT_ARGS)

engineering-test:
	bash scripts/engineering/test.sh all-safe

# Fail-closed secret scan — never pass --warn-only here.
engineering-secrets:
	bash scripts/engineering/check-secrets.sh

# CI convenience: preflight --ci + test profiles + strict secrets.
engineering-ci:
	bash scripts/engineering/preflight.sh --ci
	bash scripts/engineering/test.sh all-safe
	bash scripts/engineering/check-secrets.sh
