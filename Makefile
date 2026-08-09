.DEFAULT_GOAL := help
PY ?= python3

# Every target is declared here. A target that is not phony is skipped when a path of the same
# name exists, and make then reports "up to date" without running the recipe — a gate that never
# runs is indistinguishable from a gate that passes. `tests/test_makefile_phony.py` fails when a
# target is missing from this list, because the omission is invisible at the point it matters.
.PHONY: help lint markdown python format-python cfn i18n-check switcher-check switcher-write \
        audit secrets pinning links links-external budget en-lang counts test all new-pattern \
        commit-gate clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

lint: markdown python cfn ## Markdown lint + Python lint + CloudFormation lint

RUFF_PINNED := $(shell sed -n 's/^ruff==//p' requirements-dev.txt)

python: ## Lint and format-check tools/ and scripts/ (falls back to a syntax check)
	@if command -v ruff >/dev/null 2>&1; then \
		installed=$$(ruff --version | awk '{print $$2}'); \
		if [ "$$installed" != "$(RUFF_PINNED)" ]; then \
			echo "warning: ruff $$installed installed, this repository pins $(RUFF_PINNED)."; \
			echo "         Rule sets differ between versions, so a local pass does not"; \
			echo "         mean CI passes. Install the pinned version:"; \
			echo "         pip install -r requirements-dev.txt"; \
		fi; \
		ruff check tools scripts tests && ruff format --check tools scripts tests; \
	else \
		echo "ruff not installed - falling back to a syntax check"; \
		echo "  install the pinned version: pip install -r requirements-dev.txt"; \
		$(PY) -m py_compile tools/*.py scripts/*.py tests/*.py && echo "python: all modules compile"; \
	fi

format-python: ## Apply ruff formatting to tools/, scripts/ and tests/
	@ruff format tools scripts tests && ruff check --fix tools scripts tests

markdown: ## Run markdownlint if available (skipped when not installed)
	@if command -v markdownlint-cli2 >/dev/null 2>&1; then \
		markdownlint-cli2 "**/*.md" "#node_modules" "#.private" "#.kiro" "#.pytest_cache" "#.ruff_cache"; \
	else \
		echo "markdownlint-cli2 not installed - skipping (npm install -g markdownlint-cli2)"; \
	fi

cfn: ## Lint every pattern template (skipped when cfn-lint is not installed)
	@if ! command -v cfn-lint >/dev/null 2>&1; then \
		echo "cfn-lint not installed - skipping (pip install -r requirements-dev.txt)"; \
	else \
		found=$$(find patterns -name template.yaml -print 2>/dev/null); \
		if [ -z "$$found" ]; then \
			echo "cfn: no template.yaml under patterns/ yet"; \
		else \
			cfn-lint --non-zero-exit-code error $$found && echo "cfn: templates clean"; \
		fi; \
	fi

i18n-check: ## Check Tier 1 section parity between Japanese and English
	@$(PY) tools/check_i18n_parity.py

switcher-check: ## Verify language switchers, and that no page links to the wrong language
	@$(PY) tools/sync_lang_switcher.py

switcher-write: ## Regenerate language switcher blocks from what exists on disk
	@$(PY) tools/sync_lang_switcher.py --write

audit: ## Pre-publication audit (naming / vendor-ref / neutrality / PII / conflation)
	@$(PY) tools/audit_public_output.py

secrets: ## Secret scan (skipped when gitleaks is not installed)
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --no-git --source . --redact --exit-code 1; \
	else \
		echo "gitleaks not installed - skipping (brew install gitleaks)"; \
	fi

pinning: ## Every GitHub Action must be pinned to a commit SHA
	@$(PY) tools/check_actions_pinning.py

links: ## Check internal link resolution
	@$(PY) tools/check_links.py

links-external: ## Check internal + external links (network required)
	@$(PY) tools/check_links.py --external

budget: ## AGENTS.md size budget and steering loader reachability
	@$(PY) tools/check_agent_context_budget.py

en-lang: ## Catch untranslated Japanese in docs/en/
	@$(PY) tools/check_en_doc_language.py

counts: ## Verify every count stated in prose against the filesystem
	@$(PY) tools/check_derived_counts.py

test: ## Run every discovered test directory, one pytest process each
	@$(PY) scripts/run_tests.py

all: lint i18n-check switcher-check audit secrets pinning links budget en-lang counts test ## Commit gate
	@echo "All checks passed."

commit-gate: ## Check a message or branch name. Usage: make commit-gate MSG="docs: ..." BRANCH=docs/x
	@test -n "$(MSG)$(BRANCH)" || (echo 'give MSG="<subject>" and/or BRANCH=<name>'; exit 1)
	@$(PY) scripts/commit_gate.py $(if $(MSG),--message "$(MSG)") $(if $(BRANCH),--branch "$(BRANCH)")

new-pattern: ## Scaffold a pattern. Usage: make new-pattern AXIS=collect SLUG=my-slug
	@test -n "$(AXIS)" || (echo "AXIS is required (collect | serve | pipelines)"; exit 1)
	@test -n "$(SLUG)" || (echo "SLUG is required (e.g. SLUG=s3ap-ingest)"; exit 1)
	@$(PY) scripts/scaffold_pattern.py --axis "$(AXIS)" --slug "$(SLUG)"

clean: ## Remove local caches and previews
	@rm -rf .ruff_cache .pytest_cache __pycache__ tools/__pycache__ scripts/__pycache__ \
		tests/__pycache__ tmp-previews
	@find . -name '.DS_Store' -delete
	@echo "Cleaned."
