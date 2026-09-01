"""Loader and matcher for the vendored gitleaks ruleset — the engine
`repo_secret_scan` (`secret_scan.py`) drives. Split out of the surveyor
module itself so the ruleset-loading/matching/self-test concerns (which
have nothing to do with `StepOutcome`/`Annotation`/registry persistence)
are independently testable and, per design §1, independently swappable —
"an organisation with its own compliance requirements must be able to
point this codebase at a different ruleset without touching RE code": the
`SecretRuleset` this module builds is parameterised entirely by
`toml_path`, so pointing at a different vendored file is a config change,
not a code change.

**Vendoring shape chosen: rules-only data file, not a shelled-out binary**
(design §1's two legitimate paths). The ruleset itself lives at
`resource_explorer/configdata/vendored/gitleaks/gitleaks.toml`, pulled
verbatim from upstream — see `PROVENANCE.md` next to it for the exact
commit/date/license this was pulled at. This module reads it with the
stdlib `tomllib` (no new dependency) and matches with Python's own `re`
engine (not RE2, which is what gitleaks itself uses — a real, named
difference: a small number of gitleaks' 222 regexes could in principle
behave differently under backtracking `re` than under RE2's linear-time
engine, most plausibly as a performance difference on pathological input
rather than a correctness one, since none of the vendored regexes were
authored assuming RE2-only syntax. Not measured here; flagged in the
task's final report as an open, non-blocking risk).

**keywords are gitleaks' own pre-filter, reused for the same reason
gitleaks uses them: 222 regexes run once per non-excluded file, without a
keyword pre-filter, is a full regex sweep per file. Each rule's `keywords`
(lower-cased literal substrings from its own value's context) already ship
in the vendored TOML; a rule is even attempted only when at least one of
its keywords appears in the file content (case-insensitively) first.

**Measured, not assumed: 26 of the 222 vendored rules fail to compile
under Python's `re` and are skipped, loudly (one `log.warning` per rule,
naming it), not silently.** All 26 use syntax RE2 accepts and Python's
`re` does not — inline flags placed mid-pattern (`(?i)` other than at the
very start, which Python 3.11+ rejects outright) or a backslash-z-style anchor
`re` does not recognise. `load_ruleset()` drops exactly these and keeps
the other 196 (measured 2026-09-01, against the commit pinned in
`RULESET_VERSION` below) — the dropped rule ids are visible in this
module's own log output, not just this comment, so a future ruleset pull
that drops a different set is loud rather than a silent coverage
regression. This is the real, named cost of the "own regex engine" half of
the "vendored data file, own matcher" design choice — 196/222 (88%) rule
coverage today, not 100%, and worth surfacing per-rule if a future
iteration wants tighter parity (a Python-syntax rewrite of the 26, or a
switch to the `regex`/`re2`-bound third-party packages, neither attempted
here).
"""
from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_RULESET_PATH = (
    Path(__file__).resolve().parents[2] / "configdata" / "vendored" / "gitleaks" / "gitleaks.toml"
)

#: PROVENANCE.md's own recorded values — kept here too, deliberately
#: duplicated rather than parsed out of the markdown, because a markdown
#: file is for a human reader and this is what a running program needs to
#: stamp on every finding. If the vendored TOML is refreshed, update BOTH
#: this and PROVENANCE.md — see that file's own "Updating this vendored
#: copy" section.
RULESET_PROVIDER_NAME = "gitleaks"
RULESET_SOURCE_URL = "https://github.com/gitleaks/gitleaks"
#: The upstream commit that last touched config/gitleaks.toml at pull time
#: (2026-09-01) — this is the precise version pin (see PROVENANCE.md).
RULESET_VERSION = "09242ce9c8a60d9b051fc2d166f9e849b88c7ac0"
#: The date THAT COMMIT was made (2025-11-20), not the date it was pulled
#: into this repo — ruleset_freshness measures from when the rules
#: themselves were last changed upstream, not from when RE happened to
#: vendor them.
RULESET_AS_OF_DATE = "2025-11-20"

#: A vendored secret-pattern ruleset "wants a longer window ... closer to
#: 'has a new major version shipped upstream' than to a calendar cutoff"
#: (design §1) — left as a real decision for whoever tunes this, not
#: resolved here to a specific number backed by data. 180 days (~6 months)
#: is a deliberately longer window than security_summary's 30-day one,
#: chosen because gitleaks ships new rules on roughly a monthly cadence
#: historically, so 30 days would flag "stale" on nearly every real run.
RULESET_STALENESS_THRESHOLD_DAYS = 180


@dataclass(frozen=True)
class SecretRule:
    rule_id: str
    description: str
    pattern: re.Pattern
    keywords: tuple[str, ...]   # already lower-cased


@dataclass(frozen=True)
class SecretMatch:
    rule_id: str
    description: str
    path: str
    line: int
    #: Truncated/masked — see mask_excerpt(). Never the raw matched text.
    excerpt: str


@dataclass
class SecretRuleset:
    """A loaded, ready-to-scan ruleset. Construct via `load_ruleset()`."""

    rules: list[SecretRule]
    #: Compiled path-exclusion regexes from the TOML's own `[allowlist]`
    #: (gitleaks' own default ignore-paths — design §1: "most standard
    #: rulesets ... ship their own default ignore-paths that should be
    #: honoured rather than re-invented").
    excluded_path_patterns: list[re.Pattern]
    #: Global value-shaped noise regexes (placeholders, template tokens) —
    #: gitleaks' own `[allowlist].regexes`, applied to a candidate match's
    #: matched text before it counts as a hit.
    excluded_value_patterns: list[re.Pattern]
    source_path: Path

    def is_excluded_path(self, rel_path: str) -> bool:
        p = rel_path.replace("\\", "/")
        return any(pat.search(p) for pat in self.excluded_path_patterns)

    def _value_is_noise(self, value: str) -> bool:
        return any(pat.search(value) for pat in self.excluded_value_patterns)

    def scan_text(self, rel_path: str, text: str) -> list[SecretMatch]:
        """All matches in one file's content. `rel_path` is used only for
        the excerpt's path field — the exclusion check itself is the
        caller's responsibility (scan_paths applies it before reading
        content at all, since an excluded path shouldn't even be opened)."""
        matches: list[SecretMatch] = []
        lowered = text.lower()
        for rule in self.rules:
            if rule.keywords and not any(kw in lowered for kw in rule.keywords):
                continue
            for m in rule.pattern.finditer(text):
                value = m.group(0)
                if self._value_is_noise(value):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                matches.append(SecretMatch(
                    rule_id=rule.rule_id, description=rule.description,
                    path=rel_path, line=line, excerpt=mask_excerpt(value),
                ))
        return matches

    def scan_paths(self, root: Path, rel_paths: list[str]) -> tuple[list[SecretMatch], int, int]:
        """Scans every non-excluded path under `root`. Returns
        (matches, files_scanned, files_excluded) — both counts are
        corroborating detail, per design §1, never the known-positive
        themselves."""
        matches: list[SecretMatch] = []
        scanned = 0
        excluded = 0
        for rel in rel_paths:
            if self.is_excluded_path(rel):
                excluded += 1
                continue
            full = root / rel
            try:
                if not full.is_file():
                    continue
                text = full.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                log.debug("secret_scan: could not read %s: %s", rel, exc)
                continue
            scanned += 1
            matches.extend(self.scan_text(rel, text))
        return matches, scanned, excluded

    def provider_info(self):
        from resource_explorer.surveyors.sub_surveyors.provider_meta import (
            VENDORED_RULESET,
            ProviderInfo,
        )
        return ProviderInfo(
            provider_name=RULESET_PROVIDER_NAME,
            provider_kind=VENDORED_RULESET,
            version_or_as_of=RULESET_VERSION,
            source_url=RULESET_SOURCE_URL,
        )


def mask_excerpt(value: str, *, keep: int = 4, max_len: int = 40) -> str:
    """Truncates AND masks a matched value before it is ever persisted —
    design §1: "a survey step that persists the plaintext secret it just
    found would be creating the exact incident it exists to flag." Keeps
    only the first/last `keep` characters, unconditionally, regardless of
    how short the match is — a short match fully unmasked is still a
    stored secret."""
    v = value.strip()
    if len(v) <= keep * 2:
        masked = "*" * len(v)
    else:
        masked = v[:keep] + "*" * (len(v) - keep * 2) + v[-keep:]
    return masked[:max_len]


class RulesetUnavailable(Exception):
    """The vendored ruleset file is missing or unparseable — the
    'no scanner binary and no data-file fallback' case design §1 requires
    to become SKIPPED_BY_DESIGN, never a silent NO_SIGNAL."""


def load_ruleset(toml_path: Path | str | None = None) -> SecretRuleset:
    path = Path(toml_path) if toml_path is not None else DEFAULT_RULESET_PATH
    if not path.is_file():
        raise RulesetUnavailable(
            f"vendored ruleset data file not found at {path} — this deployment "
            "appears to have omitted the vendored asset")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise RulesetUnavailable(f"vendored ruleset at {path} could not be parsed: {exc}") from exc

    rules: list[SecretRule] = []
    for raw in data.get("rules", []):
        rule_id = raw.get("id")
        regex = raw.get("regex")
        if not rule_id or not regex:
            continue
        try:
            pattern = re.compile(regex)
        except re.error as exc:
            log.warning("secret_ruleset: skipping rule %r — regex would not compile "
                        "under Python's re engine (gitleaks itself uses RE2): %s",
                        rule_id, exc)
            continue
        keywords = tuple(str(k).lower() for k in raw.get("keywords", []) or [])
        rules.append(SecretRule(
            rule_id=rule_id, description=raw.get("description", ""),
            pattern=pattern, keywords=keywords,
        ))

    excluded_paths: list[re.Pattern] = []
    excluded_values: list[re.Pattern] = []
    allowlist = data.get("allowlist", {})
    for raw_pat in allowlist.get("paths", []) or []:
        try:
            excluded_paths.append(re.compile(raw_pat))
        except re.error as exc:
            log.debug("secret_ruleset: skipping unparseable allowlist path regex: %s", exc)
    for raw_pat in allowlist.get("regexes", []) or []:
        try:
            excluded_values.append(re.compile(raw_pat))
        except re.error as exc:
            log.debug("secret_ruleset: skipping unparseable allowlist value regex: %s", exc)

    if not rules:
        raise RulesetUnavailable(
            f"vendored ruleset at {path} parsed but yielded zero usable rules — "
            "treating as unavailable rather than scanning with an empty ruleset")

    return SecretRuleset(
        rules=rules, excluded_path_patterns=excluded_paths,
        excluded_value_patterns=excluded_values, source_path=path,
    )


# ── Known-positive self-test fixture ────────────────────────────────────
#
# design §1: "prefer running the vendored ruleset's own shipped fixtures
# over a mere scanned-file count ... Running the scanner over that
# fixture ... is a direct proof the method fired correctly on THIS run."
#
# **Honest limitation, stated here rather than only in the task report:**
# gitleaks does ship its own test corpus (`testdata/` in the upstream
# repo), but it is shaped for gitleaks' own Go test suite (paired
# fixture-file + expected-JSON-report pairs consumed by Go test code), not
# a portable "run this content through any matcher and check rule IDs
# fired" format. Reusing it as-is would mean vendoring and interpreting
# gitleaks' Go test harness, not just its rules. What follows instead is a
# small SELF-AUTHORED fixture — built from well-known, publicly-documented
# EXAMPLE credential shapes (not fabricated at random) for four of the 222
# vendored rules, chosen for regex simplicity and to avoid the ruleset's
# own built-in EXAMPLE-suffix allowlist (aws-access-token allowlists any
# value ending "EXAMPLE" — using AWS's own doc example key would silently
# not match and defeat the self-test's purpose). This proves the loader +
# matcher + keyword-prefilter + exclusion pipeline actually fires on THIS
# run; it does not prove gitleaks' own upstream test corpus still passes
# against a newer pull of the ruleset, which is a materially weaker claim
# than "ran the vendored ruleset's own fixtures" and is named as such.
_SELF_TEST_FIXTURE = "\n".join([
    'aws_key = "AKIATESTFAKEKEY2345Q"',
    'gh_token = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"',
    "-----BEGIN RSA PRIVATE KEY-----",
    "MIIEowIBAAKCAQEAfakefakefakefakefakefakefakefakefakefakefakefake",
    "fakefakefakefakefakefakefakefakefakefakefakefakefakefakefakefake",
    "-----END RSA PRIVATE KEY-----",
    'slack_app_token = "xapp-1-A1B2C3-1234567890-abc123def456"',
])

#: rule_id -> whether the self-test fixture above is expected to trigger it.
#: Kept as its own frozenset (rather than inferring "whatever fired") so a
#: rule silently dropping out of the vendored TOML on a future pull (a
#: renamed/removed upstream rule id) is a detectable self-test FAILURE
#: rather than a quietly-shrinking expectation.
_SELF_TEST_EXPECTED_RULE_IDS = frozenset({
    "aws-access-token", "github-pat", "private-key", "slack-app-token",
})


@dataclass(frozen=True)
class SelfTestResult:
    passed: bool
    expected_rule_ids: frozenset
    matched_rule_ids: frozenset
    missing_rule_ids: frozenset


def run_self_test(ruleset: SecretRuleset) -> SelfTestResult:
    """Scans the fixture above and checks every expected rule fired.
    Passing does not certify EVERY one of the 222 rules works — only that
    the load/match/keyword-prefilter pipeline is alive and that these four
    representative rule ids, spanning distinct regex shapes (a prefix+
    charset token, a fixed-prefix token, a multi-line PEM block, and a
    hyphen-delimited token), still fire end to end."""
    matches = ruleset.scan_text("__self_test_fixture__", _SELF_TEST_FIXTURE)
    matched_ids = frozenset(m.rule_id for m in matches)
    missing = _SELF_TEST_EXPECTED_RULE_IDS - matched_ids
    return SelfTestResult(
        passed=not missing,
        expected_rule_ids=_SELF_TEST_EXPECTED_RULE_IDS,
        matched_rule_ids=matched_ids & _SELF_TEST_EXPECTED_RULE_IDS,
        missing_rule_ids=missing,
    )
