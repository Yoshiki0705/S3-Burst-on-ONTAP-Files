.DEFAULT_GOAL := help
PY ?= python3

# Every target is declared here. A target that is not phony is skipped when a path of the same
# name exists, and make then reports "up to date" without running the recipe — a gate that never
# runs is indistinguishable from a gate that passes. `tests/test_makefile_gates.py` fails when a
# target is missing from this list, because the omission is invisible at the point it matters.
.PHONY: help lint markdown python format-python cfn i18n-check switcher-check switcher-write blog-sync \
        audit secrets pinning zizmor links links-external interconnect-regions budget en-lang xlang counts \
        pattern-status iac-security drift external-anchors test all new-pattern \
        diagrams diagrams-check \
        terraform finops finops-write sg-descriptions \
        commit-gate ready pr-verify clean

help: ## Show available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

lint: markdown python cfn sg-descriptions terraform ## Markdown, Python, CloudFormation and Terraform

# `RUFF` and `ZIZMOR` are overridable so that the recipes below can be driven against a stub
# binary. The defect they guard against lives in the recipe's shell, not in any Python, so a test
# that reimplements the same logic cannot reach it -- see tests/test_makefile_toolchain_checks.py.
RUFF ?= ruff
RUFF_PINNED := $(shell sed -n 's/^ruff==//p' requirements-dev.txt)

# The version is read without a pipe. `$(RUFF) --version | awk '{print $$2}'` reports the status of
# awk, which succeeds on empty input, so a binary that is installed but cannot run produced an empty
# version and fell through to the comparison below -- printing "ruff  installed, this repository
# pins 0.15.20" and pointing at the version pin. That named the wrong remedy: the install is broken,
# not mismatched. stderr is deliberately not suppressed, because the binary's own message (a missing
# shared library, typically) is the useful part of the diagnosis.
python: ## Lint and format-check tools/ and scripts/ (falls back to a syntax check)
	@if command -v $(RUFF) >/dev/null 2>&1; then \
		if ! raw=$$($(RUFF) --version); then \
			echo "error: $(RUFF) is present but does not run - '--version' exited non-zero."; \
			echo "       Its own error is above. This is a broken install, not a version"; \
			echo "       mismatch, so pinning will not fix it:"; \
			echo "       pip install --force-reinstall -r requirements-dev.txt"; \
			exit 1; \
		fi; \
		if [ -z "$$raw" ]; then \
			echo "error: $(RUFF) ran but reported no version, so the pin cannot be checked."; \
			exit 1; \
		fi; \
		installed=$${raw##* }; \
		if [ "$$installed" != "$(RUFF_PINNED)" ]; then \
			echo "warning: ruff $$installed installed, this repository pins $(RUFF_PINNED)."; \
			echo "         Rule sets differ between versions, so a local pass does not"; \
			echo "         mean CI passes. Install the pinned version:"; \
			echo "         pip install -r requirements-dev.txt"; \
		fi; \
		$(RUFF) check tools scripts tests && $(RUFF) format --check tools scripts tests; \
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

# `template.yaml` is the deployable template of a pattern, and `examples/*.yaml` are the reference
# templates beside it. Both are linted; only the first is counted as a pattern by `make counts`,
# which is what keeps "one pattern, one template" true while a pattern can still carry examples.
#
# The examples were added to this scan at the same time as the first pattern that has any. A file
# that reads like a template and is linted by nothing is the shape that rots: it is copied, and the
# copy is the first thing anybody validates.
cfn: ## Lint every CloudFormation template and example (skipped when cfn-lint is not installed)
	@if ! command -v cfn-lint >/dev/null 2>&1; then \
		echo "cfn-lint not installed - skipping (pip install -r requirements-dev.txt)"; \
	else \
		if ! found=$$(find patterns environments \( -name template.yaml -o -path '*/examples/*.yaml' \) -print); then \
			echo "cfn: the scan of patterns/ and environments/ failed, so this is not a report"; \
			echo "     that there are no templates. Its own error is above."; \
			exit 1; \
		fi; \
		if [ -z "$$found" ]; then \
			echo "cfn: no template.yaml anywhere under patterns/ or environments/. Both are"; \
			echo "     tracked and contain some, so zero means this scan stopped matching,"; \
			echo "     not that there is nothing to lint."; \
			exit 1; \
		fi; \
		cfn-lint --non-zero-exit-code error $$found && echo "cfn: templates clean"; \
	fi

sg-descriptions: ## Security group rule descriptions must use only characters EC2 accepts
	@$(PY) tools/check_sg_rule_descriptions.py

terraform: ## Validate and format-check every Terraform root (skipped when terraform is absent)
	@if ! command -v terraform >/dev/null 2>&1; then \
		echo "terraform not installed - skipping (brew install terraform)"; \
	else \
		if ! found=$$(find environments -name '*.tf' -print); then \
			echo "terraform: the scan of environments/ failed, so this is not a report that"; \
			echo "           there is nothing to validate. Its own error is above."; \
			exit 1; \
		fi; \
		if [ -z "$$found" ]; then \
			echo "terraform: no .tf file under environments/. The tracked roots contain some,"; \
			echo "           so zero means this scan stopped matching, not 'none yet'."; \
			exit 1; \
		fi; \
		roots=$$(printf '%s\n' "$$found" | sed 's|/[^/]*$$||' | sort -u); \
		if [ -z "$$roots" ]; then \
			echo "terraform: found .tf files but derived no directory from their paths."; \
			exit 1; \
		else \
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

# There is deliberately no `slides` target. The LT deck and its generator both live under
# `.private/`, which is gitignored, because the generator contains the deck's text. A target
# pointing at a gitignored path is a broken target in a fresh clone.
# Run it directly:  python3 .private/slides/build_slides.py

audit: ## Pre-publication audit (naming / vendor-ref / neutrality / PII / conflation)
	@$(PY) tools/audit_public_output.py

secrets: ## Secret scan (skipped when gitleaks is not installed)
	@if command -v gitleaks >/dev/null 2>&1; then \
		gitleaks detect --no-git --source . --config .gitleaks.toml --redact --exit-code 1; \
	else \
		echo "gitleaks not installed - skipping (brew install gitleaks)"; \
	fi

# Frameworks are named rather than left to auto-detection: checkov also parses the Python under
# tools/ and scripts/ as generic IaC on some versions, and a gate whose scope changes with the version
# cannot tell you whether your change is clean. The Terraform under environments/onprem-cache/ uses
# the netapp-ontap provider, for which checkov has no policies, so naming frameworks also stops that
# directory being reported as zero-of-zero and read as covered.
iac-security: ## Security posture of the templates and workflows (skipped when checkov is absent)
	@if command -v checkov >/dev/null 2>&1; then \
		checkov -d . --framework cloudformation --framework github_actions \
		  --compact --quiet --skip-download; \
	else \
		echo "checkov not installed - skipping (pip install -r requirements-dev.txt)"; \
	fi

pinning: ## Every GitHub Action must be pinned to a commit SHA
	@$(PY) tools/check_actions_pinning.py

ZIZMOR ?= zizmor
ZIZMOR_PINNED := $(shell sed -n 's/^zizmor==//p' requirements-dev.txt)
# Read without a pipe, for the reason given above `python`.
zizmor: ## Audit the workflow files for CI security problems
	@if command -v $(ZIZMOR) >/dev/null 2>&1; then \
		if ! raw=$$($(ZIZMOR) --version); then \
			echo "error: $(ZIZMOR) is present but does not run - '--version' exited non-zero."; \
			echo "       Its own error is above. This is a broken install, not a version"; \
			echo "       mismatch, so pinning will not fix it:"; \
			echo "       pip install --force-reinstall -r requirements-dev.txt"; \
			exit 1; \
		fi; \
		if [ -z "$$raw" ]; then \
			echo "error: $(ZIZMOR) ran but reported no version, so the pin cannot be checked."; \
			exit 1; \
		fi; \
		installed=$${raw##* }; \
		if [ "$$installed" != "$(ZIZMOR_PINNED)" ]; then \
			echo "warning: zizmor $$installed installed, this repository pins $(ZIZMOR_PINNED)."; \
			echo "         Rule sets differ between versions, so a local pass does not"; \
			echo "         mean CI passes. Install the pinned version:"; \
			echo "         pip install -r requirements-dev.txt"; \
		fi; \
		$(ZIZMOR) --no-online-audits --no-progress --persona=pedantic .github/workflows; \
	else \
		echo "zizmor not installed - skipping"; \
		echo "  install the pinned version: pip install -r requirements-dev.txt"; \
	fi

links: ## Check internal link resolution
	@$(PY) tools/check_links.py

links-external: ## Check internal + external links (network required)
	@$(PY) tools/check_links.py --external
# Deliberately outside `all`. It reads someone else's page, so it would make the commit gate depend
# on the network and turn red on a pull request that changed nothing. Scheduled weekly instead,
# alongside link-rot, for the same reason.
interconnect-regions: ## Compare the Interconnect Region pairs against AWS's page (network required)
	@$(PY) tools/check_interconnect_regions.py

budget: ## AGENTS.md size budget and steering loader reachability
	@$(PY) tools/check_agent_context_budget.py

en-lang: ## Catch untranslated Japanese in docs/en/
	@$(PY) tools/check_en_doc_language.py

counts: ## Verify every count stated in prose against the filesystem
	@$(PY) tools/check_derived_counts.py

blog-sync: ## Verify no blog draft has moved ahead of its published post
	@$(PY) tools/check_blog_draft_sync.py

drift: ## Compare the contents of translated tables, not just their headings
	@$(PY) tools/check_translation_drift.py

external-anchors: ## Verify cited sibling-repository anchors (skipped without a local checkout)
	@$(PY) tools/check_external_anchors.py

pattern-status: ## Verify every pattern README opens with a defined status word
	@$(PY) tools/check_pattern_status.py

finops: ## Verify the generated cost tables match the model
	@$(PY) tools/finops_model.py --check

finops-write: ## Regenerate the cost tables from the model
	@$(PY) tools/finops_model.py --write

test: ## Run every discovered test directory, one pytest process each
	@$(PY) scripts/run_tests.py

all: lint i18n-check switcher-check xlang drift external-anchors audit secrets pinning zizmor links budget en-lang counts blog-sync pattern-status iac-security finops test ## Commit gate
	@echo "All checks passed."

pr-verify: ## Confirm CI passed for the commit a PR currently points at (needs PR=<n>)
	@test -n "$(PR)" || { echo "usage: make pr-verify PR=<number>"; exit 2; }
	@$(PY) scripts/verify_pr_checks.py $(PR)

commit-gate: ## Check a message or branch name. Usage: make commit-gate MSG="docs: ..." BRANCH=docs/x
	@test -n "$(MSG)$(BRANCH)" || (echo 'give MSG="<subject>" and/or BRANCH=<name>'; exit 1)
	@$(PY) scripts/commit_gate.py $(if $(MSG),--message "$(MSG)") $(if $(BRANCH),--branch "$(BRANCH)")

# The one target to run before committing. `commit-gate` on its own only checks the subject line, so
# invoking it satisfies a habit without covering the work; this depends on `all` as well, so a single
# `&&` links a complete gate to the commit.
#
# Two ways the separation used to leak, both structural rather than forgetful:
#   make all; git commit ...            -- `;` does not carry the failure
#   make all 2>&1 | tail -2 && git ...  -- the pipeline's status is tail's, which is 0
# So: `make ready MSG="..." && git commit -F <file>`, no pipe on the left.
ready: all ## Full gate plus the commit message check. Usage: make ready MSG="docs: ..."
	@test -n "$(MSG)" || (echo 'give MSG="<subject>"'; exit 1)
	@$(PY) scripts/commit_gate.py --message "$(MSG)"
	@echo "ready: gates green and the subject is valid - commit with && from here"

new-pattern: ## Scaffold a pattern. Usage: make new-pattern AXIS=collect SLUG=my-slug
	@test -n "$(AXIS)" || (echo "AXIS is required (collect | serve | pipelines)"; exit 1)
	@test -n "$(SLUG)" || (echo "SLUG is required (e.g. SLUG=s3ap-ingest)"; exit 1)
	@$(PY) scripts/scaffold_pattern.py --axis "$(AXIS)" --slug "$(SLUG)"

clean: ## Remove local caches and previews
	@rm -rf .ruff_cache .pytest_cache __pycache__ tools/__pycache__ scripts/__pycache__ \
		tests/__pycache__ tmp-previews
	@find . -name '.DS_Store' -delete
	@echo "Cleaned."
