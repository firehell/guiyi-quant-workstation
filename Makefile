# OPTIONAL / NON-CANONICAL
#
# Windows PowerShell 7 scripts under scripts/engineering/*.ps1 are the
# canonical engineering entrypoints. This Makefile is retained only as an
# optional non-Windows convenience and must not be treated as authorization
# or as the documented developer workflow.
#
# Prefer:
#   pwsh -NoProfile -File ./scripts/engineering/preflight.ps1
#   pwsh -NoProfile -File ./scripts/engineering/validate.ps1 -Profile Engineering
#   pwsh -NoProfile -File ./scripts/engineering/secret-scan.ps1

.PHONY: engineering-preflight engineering-test engineering-secrets

engineering-preflight:
	@echo "DEPRECATED: use pwsh scripts/engineering/preflight.ps1" >&2
	pwsh -NoProfile -File scripts/engineering/preflight.ps1

engineering-test:
	@echo "DEPRECATED: use pwsh scripts/engineering/validate.ps1 -Profile Engineering" >&2
	pwsh -NoProfile -File scripts/engineering/validate.ps1 -Profile Engineering

engineering-secrets:
	@echo "DEPRECATED: use pwsh scripts/engineering/secret-scan.ps1" >&2
	pwsh -NoProfile -File scripts/engineering/secret-scan.ps1
