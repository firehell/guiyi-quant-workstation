.PHONY: engineering-preflight engineering-test engineering-secrets engineering-ci

# Local default: ordinary preflight (branch warn on main, dirty warn).
# CI: make engineering-preflight ENGINEERING_PREFLIGHT_ARGS=--ci
ENGINEERING_PREFLIGHT_ARGS ?=

# Default profile is CI-safe (no uv/fastapi). Local full suite:
#   make engineering-test ENGINEERING_TEST_PROFILE=all-safe
ENGINEERING_TEST_PROFILE ?= engineering

engineering-preflight:
	bash scripts/engineering/preflight.sh $(ENGINEERING_PREFLIGHT_ARGS)

engineering-test:
	bash scripts/engineering/test.sh $(ENGINEERING_TEST_PROFILE)

# Fail-closed secret scan — never pass --warn-only here.
engineering-secrets:
	bash scripts/engineering/check-secrets.sh

# CI convenience: preflight --ci + engineering profile + strict secrets.
engineering-ci:
	bash scripts/engineering/preflight.sh --ci
	bash scripts/engineering/test.sh engineering
	bash scripts/engineering/check-secrets.sh
