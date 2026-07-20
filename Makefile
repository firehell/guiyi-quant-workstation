.PHONY: engineering-preflight engineering-test workstation-doctor workstation-test

engineering-preflight:
	bash scripts/engineering/preflight.sh
	bash scripts/engineering/check-secrets.sh

engineering-test: engineering-preflight
	bash scripts/engineering/test.sh

# Compatibility aliases (deprecated names)
workstation-doctor: engineering-preflight

workstation-test: engineering-test
