"""Every writing-style rule fires on its positive and stays silent on its negative.

Adapted from the Hub (`FSx-for-ONTAP-Adoption-Playbook`, `scripts/tests/test_ai_style_rules.py`).
The spoke lays its tests flat under `tests/`, and `tests/conftest.py` puts `tools/` on `sys.path`,
so `ai_style_rules` and `audit_public_output` are imported directly rather than as `tools.<name>`.

The examples live on the rules themselves (`Rule.positive` / `Rule.negative` in
`tools/ai_style_rules.py`), because the copyable file's `--selftest` needs them too and two copies
of one example set drift. This file adds what a selftest cannot say about itself: that every rule
has examples at all, that non-prose spans are excluded, that languages are kept apart, and that the
audit gates on ai-style (D1 / D2 / D5 / D14) and keeps ai-style-warn counted but never gating
(FEAT-003 fixed the D1 corpus and emptied REPORT_ONLY_CATEGORIES).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import ai_style_rules as rules
import audit_public_output as audit

BROKEN = "上は**「自分の構成」**で引く。\n"
RENDERED = "次は**自分の構成**で引く。\n"
# Enough kana for language_of to read a file with no language in its path as Japanese.
JA_LEAD = "これはひらがなを十分に含む日本語の段落です。\n\n"


def rule_ids(document: str, lang: str = "ja") -> set[str]:
    return {finding.rule for finding in rules.scan_markdown(document, lang)}


class EachRuleHasAPositiveAndANegative(unittest.TestCase):
    def test_every_rule_carries_examples(self) -> None:
        """A rule added without examples has no evidence that it can fire or stay quiet."""
        for rule in rules.RULES:
            with self.subTest(rule=rule.id):
                self.assertTrue(rule.positive, f"{rule.id} has no positive example")
                self.assertTrue(rule.negative, f"{rule.id} has no negative example")
                self.assertIn(rule.level, rules.CATEGORY_FOR_LEVEL)
                self.assertTrue(
                    rule.defect, f"{rule.id} does not name the defect it suggests"
                )

    def test_positives_fire(self) -> None:
        for rule in rules.RULES:
            for lang, document in rule.positive:
                with self.subTest(rule=rule.id, document=document[:40]):
                    self.assertIn(rule.id, rule_ids(document, lang))

    def test_negatives_are_silent(self) -> None:
        for rule in rules.RULES:
            for lang, document in rule.negative:
                with self.subTest(rule=rule.id, document=document[:40]):
                    self.assertNotIn(rule.id, rule_ids(document, lang))

    def test_the_fail_tier_is_exactly_the_agreed_four(self) -> None:
        fail = {rule.id for rule in rules.RULES if rule.level == "fail"}
        self.assertEqual(fail, {"D1", "D2", "D5", "D14"})

    def test_rule_ids_are_unique(self) -> None:
        ids = [rule.id for rule in rules.RULES]
        self.assertEqual(len(ids), len(set(ids)))


class NonProseIsExcluded(unittest.TestCase):
    def test_fence_code_span_comment_frontmatter_and_switcher(self) -> None:
        cases = {
            "fence": "```text\n速さが核心です。\nご不明な点があればどうぞ。\n```\n",
            "code span": "例: `速さが核心です。` と `ご不明な点` は書かない。\n",
            "comment": "<!-- 速さが核心です。ご不明な点 -->\n本文。\n",
            "multi-line comment": "<!--\n速さが核心です。\nご不明な点\n-->\n本文。\n",
            "frontmatter": "---\ntitle: 速さが核心です。\n---\n本文。\n",
            "switcher": (
                "<!-- lang-switcher:start -->\n速さが核心です。ご不明な点\n"
                "<!-- lang-switcher:end -->\n本文。\n"
            ),
        }
        for name, document in cases.items():
            with self.subTest(name=name):
                found = rule_ids(document)
                self.assertNotIn("D2", found)
                self.assertNotIn("D5", found)

    def test_d1_ignores_code(self) -> None:
        self.assertNotIn("D1", rule_ids("`" + BROKEN.strip() + "`\n"))
        self.assertNotIn("D1", rule_ids("```text\n" + BROKEN + "```\n"))

    def test_line_numbers_are_those_of_the_file(self) -> None:
        document = "---\ntitle: x\n---\n\n" + BROKEN
        lines = {f.line for f in rules.scan_markdown(document, "ja") if f.rule == "D1"}
        self.assertEqual(lines, {5})


class LanguagesAreKeptApart(unittest.TestCase):
    def test_japanese_only_rule_is_silent_in_english(self) -> None:
        self.assertNotIn("D2", rule_ids("速さが核心です。\n", "en"))

    def test_unscanned_languages_return_nothing(self) -> None:
        self.assertEqual(rules.scan_markdown(BROKEN, "ko"), [])

    def test_language_of(self) -> None:
        self.assertEqual(
            rules.language_of("docs/en/x.md", "日本語の本文です。" * 5), "en"
        )
        self.assertEqual(rules.language_of("docs/ko/x.md", ""), "ko")
        self.assertEqual(rules.language_of("README-ja.md", "English only"), "ja")
        self.assertEqual(
            rules.language_of("guide.en.md", "日本語の本文です。" * 5), "en"
        )
        self.assertEqual(
            rules.language_of("AGENTS.md", "これはひらがなとカタカナの本文です。"), "ja"
        )
        self.assertEqual(rules.language_of("AGENTS.md", "English prose only."), "en")


class CopyableCli(unittest.TestCase):
    """The module runs as a standalone CLI, which is what makes it copyable into other repos."""

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "ai_style_rules.py"), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def test_fail_flag_gates_and_default_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            note = Path(name) / "note.md"
            note.write_text(BROKEN, encoding="utf-8")
            self.assertEqual(self.run_cli(name).returncode, 0)
            self.assertEqual(self.run_cli(name, "--fail").returncode, 1)
            note.write_text(RENDERED, encoding="utf-8")
            self.assertEqual(self.run_cli(name, "--fail").returncode, 0)

    def test_markers_exclude_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "marked.md").write_text(
                BROKEN.strip() + " <!-- allow:ai-style -->\n", encoding="utf-8"
            )
            (root / "declared.md").write_text(
                "<!-- audit-file-allow: ai-style -->\n" + BROKEN, encoding="utf-8"
            )
            (root / "blog").mkdir()
            (root / "blog" / "post.md").write_text(JA_LEAD + BROKEN, encoding="utf-8")
            self.assertEqual(
                self.run_cli(name, "--fail", "--exclude", "blog/*").returncode, 0
            )
            summary = self.run_cli(name, "--summary")
            self.assertIn("| ai-style | ja | D1 | 2 |", summary.stdout)
            self.assertIn("| blog/post.md | ja | 2 | 2 |", summary.stdout)

    def test_selftest(self) -> None:
        self.assertEqual(self.run_cli("--selftest").returncode, 0)


class AuditStagesTheCategory(unittest.TestCase):
    """ai-style gates the default audit: FEAT-003 fixed the D1 corpus and emptied
    REPORT_ONLY_CATEGORIES. A fail-tier (D1 / D2 / D5 / D14) finding now fails the audit;
    ai-style-warn is counted but never gates."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_audit(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "audit_public_output.py"),
                "--path",
                str(self.root),
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )

    def test_default_audit_fails_on_a_fail_tier_finding(self) -> None:
        # D1 findings are present (the broken line leaves two literal `**` pairs). ai-style now
        # gates, so the audit returns 1, reports the finding on the `[ai-style] D1` channel, and
        # the summary counts it as fail-tier.
        self.write("note.md", BROKEN)
        result = self.run_audit()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            "audit: ai-style findings: 2 fail-tier (gated), 0 warning",
            result.stdout + result.stderr,
        )
        self.assertIn("Audit failed", result.stdout + result.stderr)
        self.assertIn("[ai-style] D1", result.stderr)

    def test_a_warning_finding_is_counted_and_does_not_gate(self) -> None:
        # An em-dash-only (D18) document is ai-style-warn: counted, never gated. With no fail-tier
        # finding the audit still returns 0 even though ai-style now gates.
        self.write("note.md", JA_LEAD + "転送 — 差分のみ\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 fail-tier (gated), 1 warning", result.stdout + result.stderr)
        self.assertNotIn("Audit failed", result.stdout + result.stderr)

    def test_a_line_marker_suppresses_the_style_category(self) -> None:
        # A line allow marker suppresses the fail-tier finding, so the gated audit returns 0.
        self.write("note.md", BROKEN.strip() + " <!-- allow:ai-style -->\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 fail-tier (gated), 0 warning", result.stdout + result.stderr)

    def test_a_file_declaration_suppresses_the_style_category(self) -> None:
        self.write("note.md", "<!-- audit-file-allow: ai-style -->\n" + BROKEN)
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 fail-tier (gated), 0 warning", result.stdout + result.stderr)

    def test_non_markdown_files_are_not_scanned_for_style(self) -> None:
        self.write("notes.txt", "速さが核心です。\n")
        self.write("config.yml", "title: 速さが核心です。\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 fail-tier (gated), 0 warning", result.stdout + result.stderr)

    def test_the_gate_constants(self) -> None:
        # FEAT-003 emptied REPORT_ONLY_CATEGORIES: ai-style is no longer staged and gates the
        # default audit. ai-style-warn stays the warning tier and is never gated.
        self.assertEqual(audit.REPORT_ONLY_CATEGORIES, frozenset())
        self.assertNotIn("ai-style", audit.REPORT_ONLY_CATEGORIES)
        self.assertIn("ai-style-warn", audit.WARNING_CATEGORIES)
        self.assertEqual(
            set(rules.CATEGORY_FOR_LEVEL.values()), {"ai-style", "ai-style-warn"}
        )

    def test_the_wiring_leaves_the_existing_categories_in_place(self) -> None:
        """ai-style is additive: the spoke's own categories and audit_line() are untouched."""
        for category in (
            "naming",
            "vendor-ref",
            "neutrality",
            "pii",
            "role-label",
            "conflation",
            "hype",
            "coinage",
        ):
            self.assertIn(category, audit.CATEGORIES)
        # A naming violation still gates through the existing audit_line path.
        self.write("bad.md", "FSxN volumes are Multi-AZ.\n")
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("[naming]", result.stderr)


if __name__ == "__main__":
    unittest.main()
