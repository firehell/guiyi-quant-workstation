.PHONY: workstation-doctor workstation-test

workstation-doctor:
	bash scripts/ai/workstation_doctor.sh --strict --skip-installed-profiles

workstation-test: workstation-doctor
	python3 -m pytest -q tests/workstation
