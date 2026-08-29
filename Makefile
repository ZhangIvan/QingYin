.PHONY: check contract-fixtures design-docs doctest format-lint rustdoc security security-release-guard unit

PYTHON ?= python3

contract-fixtures:
	$(PYTHON) scripts/validate_contract_fixtures.py
	$(PYTHON) scripts/validate_workspace_boundaries.py

design-docs:
	$(PYTHON) scripts/validate_design_assets.py
	$(PYTHON) scripts/validate_markdown_links.py

format-lint:
	cargo fmt --all --check
	cargo check --workspace --all-targets --all-features --locked
	cargo clippy --workspace --all-targets --all-features --locked -- -D warnings

rustdoc:
	RUSTDOCFLAGS="-D warnings" cargo doc --workspace --all-features --no-deps --locked

security:
	$(PYTHON) scripts/validate_secret_regressions.py
	$(PYTHON) scripts/validate_security_release_guard.py
	cargo test -p qingyin-security -p qingyin-observe --all-targets --all-features --locked

security-release-guard:
	$(PYTHON) scripts/validate_security_release_guard.py

unit:
	cargo test --workspace --all-targets --all-features --locked

doctest:
	cargo test --workspace --doc --all-features --locked

check: format-lint rustdoc unit doctest security contract-fixtures design-docs
