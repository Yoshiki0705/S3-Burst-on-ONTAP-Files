.DEFAULT_GOAL := help
PY ?= python3

# Every target is declared here. A target that is not phony is skipped when a path of the same
# name exists, and make then reports "up to date" without running the recipe — a gate that never
# runs is indistinguishable from a gate that passes. `tests/test_makefile_gates.py` fails when a
# target is missing from this list, because the omission is invisible at the point it matters.
.PHONY: help lint markdown python format-python cfn i18n-check switcher-check switcher-write \
        audit secrets pinning zizmor links links-external budget en-lang xlang counts test all new-pattern \
        diagrams diagrams-check \
        terraform finops finops-write \
        commit-gate clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

lint: markdown python cfn terraform ## Markdown, Python, CloudFormation and Terraform

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
		markdownlint-cli2 "**/*.md" "#node_modules" "#.private" "#.kiro" "#.pytest_cache" "#.ruff_cache" "#**/.terraform"; \
	else \
		echo "markdownlint-cli2 not installed - skipping (npm install -g markdownlint-cli2)"; \
	fi

cfn: ## Lint every CloudFormation template (skipped when cfn-lint is not installed)
	@if ! command -v cfn-lint >/dev/null 2>&1; then \
		echo "cfn-lint not installed - skipping (pip install -r requirements-dev.txt)"; \
	else \
		found=$$(find patterns environments -name template.yaml -print 2>/dev/null); \
		if [ -z "$$found" ]; then \
			echo "cfn: no template.yaml found yet"; \
		else \
			cfn-lint --non-zero-exit-code error $$found && echo "cfn: templates clean"; \
		fi; \
	fi

terraform: ## Validate and format-check every Terraform root (skipped when terraform is absent)
	@if ! command -v terraform >/dev/null 2>&1; then \
		echo "terraform not installed - skipping (brew install terraform)"; \
	else \
		roots=$$(find environments -name '*.tf' -exec dirname {} \; 2>/dev/null | sort -u); \
		if [ -z "$$roots" ]; then echo "terraform: no .tf files yet"; else \
			for d in $$roots; do \
				terraform -chdir="$$d" fmt -check -recursive >/dev/null || { echo "terraform: $$d is not formatted; run 'terraform -chdir=$$d fmt'"; exit 1; }; \
				if [ -d "$$d/.terraform" ]; then \
					terraform -chdir="$$d" validate || exit 1; \
				else \
					echo "terraform: $$d not initialised, checked formatting only (run 'terraform -chdir=$$d init -backend=false' to validate)"; \
				fi; \
			done; \
		fi; \
	fi

i18n-check: ## Check Tier 1 section parity between Japanese and English
	@$(PY) tools/check_i18n_parity.py

switcher-check: ## Verify language switchers, and that no page links to the wrong language
	@$(PY) tools/sync_lang_switcher.py

switcher-write: ## Regenerate language switcher blocks from what exists on disk
	@$(PY) tools/sync_lang_switcher.py --write

xlang: ## Links from English into Japanese must be marked (Japanese)
	@$(PY) tools/check_cross_language_links.py

diagrams: ## Regenerate the diagrams and export SVG + PNG (needs the AWS icon package)
	@$(PY) tools/build_diagrams.py --write --export

diagrams-check: ## Confirm the committed diagrams match their spec (needs the AWS icon package)
	@$(PY) tools/build_diagrams.py --check

audit: ## Pre-publication audit (naming / vendor-ref / neutrality / PII / conflation)
	@$(PY) tools/audit_public_output.py

secrets: ## Secret scan (skipped when gitleaks is not installed)
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --no-git --source . --config .gitleaks.toml --redact --exit-code 1; \
	else \
		echo "gitleaks not installed - skipping (brew install gitleaks)"; \
	fi

pinning: ## Every GitHub Action must be pinned to a commit SHA
	@$(PY) tools/check_actions_pinning.py

ZIZMOR_PINNED := $(shell sed -n 's/^zizmor==//p' requirements-dev.txt)
zizmor: ## Audit the workflow files for CI security problems
	@if command -v zizmor >/dev/null 2>&1; then \
		installed=$$(zizmor --version | awk '{print $$2}'); \
		if [ "$$installed" != "$(ZIZMOR_PINNED)" ]; then \
			echo "warning: zizmor $$installed installed, this repository pins $(ZIZMOR_PINNED)."; \
			echo "         Rule sets differ between versions, so a local pass does not"; \
			echo "         mean CI passes. Install the pinned version:"; \
			echo "         pip install -r requirements-dev.txt"; \
		fi; \
		zizmor --no-online-audits --persona=pedantic .github/workflows; \
	else \
		echo "zizmor not installed - skipping"; \
		echo "  install the pinned version: pip install -r requirements-dev.txt"; \
	fi

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

finops: ## Verify the generated cost tables match the model
	@$(PY) tools/finops_model.py --check

finops-write: ## Regenerate the cost tables from the model
	@$(PY) tools/finops_model.py --write

test: ## Run every discovered test directory, one pytest process each
	@$(PY) scripts/run_tests.py

all: lint i18n-check switcher-check xlang audit secrets pinning zizmor links budget en-lang counts finops test ## Commit gate
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
