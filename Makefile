.PHONY: contract-fixtures format-lint unit

contract-fixtures:
	python3 scripts/validate_contract_fixtures.py
	python3 scripts/validate_workspace_boundaries.py

format-lint:
	cargo fmt --all -- --check
	cargo clippy --workspace --all-targets -- -D warnings

unit:
	cargo test --workspace --all-targets
