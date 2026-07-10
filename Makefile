.PHONY: contract-fixtures format-lint security unit

PYTHON ?= python3

contract-fixtures:
	$(PYTHON) scripts/validate_contract_fixtures.py
	$(PYTHON) scripts/validate_workspace_boundaries.py

format-lint:
	cargo fmt --all --check
	cargo check --workspace --all-targets
	cargo clippy --workspace --all-targets -- -D warnings

security:
	$(PYTHON) scripts/validate_secret_regressions.py
	cargo test -p qingyin-security -p qingyin-observe

unit:
	cargo test --workspace --all-targets
