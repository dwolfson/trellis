"""The shared provider-provenance shape (design §0b) — ONE concept, not a
secrets-only one.

`repo_secret_scan` (this file's first, and so far only, consumer) is the
`vendored_ruleset`-flavoured instance of a shape that also fits
`cve_scan` (`live_queried_api`, OSV.dev), `license_classification` (two
`re_authored_scheme` records — the SPDX vocabulary and RE's own risk-tier
mapping), and `foss_scorecard` (`re_authored_scheme`, `CHECKS`).

**Built now, adopted later, deliberately.** Per the task brief this module
exists so `repo_secret_scan`/`repo_telemetry_scan`/`repo_contribution_
provenance`/`repo_sla_content` do not each invent their own provider-record
shape (which is exactly how `security_scan`/`security_hygiene` diverged —
see §0). `cve_scan`, `license_classification`, and `foss_scorecard` are
NOT retrofitted here — `cve_scan` in particular needs a regression fixture
pinning today's 14-finding shape on `egeria_git` before it is touched at
all (design §0b, "adopt third, and pin before touching it"). Retrofitting
those three is separately sequenced work.

**The guardrail every adoption must honour, non-negotiably** (design §0b):
these fields are added to a finding's `detail` dict — a pure addition —
never a rename of `kind`/`check_name`/the analysis id. `foss_scorecard` and
`security_summary` are live downstream readers of those exact strings
today; a provider-adoption change that touched one would not fail loudly,
it would silently narrow their inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

#: provider_kind values (design §0b's shared shape).
VENDORED_RULESET = "vendored_ruleset"
LIVE_QUERIED_API = "live_queried_api"
RE_AUTHORED_SCHEME = "re_authored_scheme"

PROVIDER_KINDS = (VENDORED_RULESET, LIVE_QUERIED_API, RE_AUTHORED_SCHEME)


class InvalidProvider(ValueError):
    """Raised when a ProviderInfo cannot be expressed — mirrors
    step_outcome.InvalidOutcome's constructor-enforced-rather-than-trusted
    approach, for the same reason: a malformed provider record is a silent
    provenance lie, not a loud failure, unless the constructor catches it."""


@dataclass(frozen=True)
class ProviderInfo:
    """One provider/scheme's identity, as recorded on every finding it
    produces — design §0b's shared shape, verbatim field names.

    `provider_name`   e.g. "gitleaks", "osv.dev", "re_foss_scorecard".
    `provider_kind`   one of PROVIDER_KINDS.
    `version_or_as_of`  a pinned version/commit for a vendored ruleset; a
                        query timestamp for a live API; a scheme-version
                        tag for an RE-authored table. Required non-empty —
                        an unstamped provider record is indistinguishable
                        from one that forgot to stamp itself, which is the
                        exact "confident wrong answer" this whole design
                        exists to prevent for the ruleset/scheme layer.
    `source_url`      where a reader can go to see the standard itself.
                       May be legitimately empty ONLY for `re_authored_
                       scheme` — design §0b's own worked example
                       (`license_classification`'s risk-tier table) says
                       an empty source_url there is itself informative
                       ("there is no external page to point to for RE's
                       own risk judgement, and saying so plainly is more
                       honest than a placeholder link"). Any other kind
                       with an empty source_url is a mistake, not a
                       legitimate absence, and the constructor rejects it.
    """

    provider_name: str
    provider_kind: str
    version_or_as_of: str
    source_url: str = ""

    def __post_init__(self) -> None:
        if self.provider_kind not in PROVIDER_KINDS:
            raise InvalidProvider(
                f"unknown provider_kind {self.provider_kind!r}; expected one of "
                f"{', '.join(PROVIDER_KINDS)}")
        if not self.provider_name:
            raise InvalidProvider("provider_name is required — an unnamed provider "
                                   "cannot be told apart from another unnamed one in "
                                   "stored history")
        if not self.version_or_as_of:
            raise InvalidProvider(
                f"version_or_as_of is required for {self.provider_name!r} — an "
                "unstamped provider record cannot answer 'checked against what, as "
                "of when', which is the whole reason this record exists")
        if not self.source_url and self.provider_kind != RE_AUTHORED_SCHEME:
            raise InvalidProvider(
                f"source_url is required for provider_kind={self.provider_kind!r} "
                f"({self.provider_name!r}) — only re_authored_scheme may legitimately "
                "have no external standard to point to")

    def as_row(self) -> dict[str, Any]:
        """The fields to fold into a finding's `detail` dict — additive
        only, per the guardrail in this module's docstring."""
        return {
            "provider_name": self.provider_name,
            "provider_kind": self.provider_kind,
            "version_or_as_of": self.version_or_as_of,
            "source_url": self.source_url,
        }


#: Staleness labels — mirrors security_summary.py's summary_freshness
#: vocabulary exactly ("current"/"stale"), plus "" for "could not be
#: determined", the same three-way shape result_status.py's whole design
#: insists on for every other absence-vs-answer distinction in this
#: codebase.
CURRENT = "current"
STALE = "stale"


@dataclass(frozen=True)
class StalenessCheck:
    """The result of asking "is this provider's pinned version too old" —
    modelled on security_summary.py's `summary_freshness` finding
    (`_age_days`, `oldest_input_age_days`), generalised to any provider
    whose staleness is measured from a recorded pull/release date rather
    than from when the analysis using it happens to run.

    Deliberately NOT how stale a `live_queried_api` provider's *coverage*
    is (design §0b: OSV can simply not know about a new advisory yet —
    "a different failure shape than staleness, not solved here"). This
    check only applies to a provider with a pinned `as_of_date` — a
    vendored ruleset or an RE-authored scheme due for periodic review.
    """

    label: str          # CURRENT | STALE | ""
    age_days: int | None
    threshold_days: int
    as_of_date: str      # ISO date the provider was pulled/authored/reviewed


def check_staleness(as_of_date: str, *, threshold_days: int) -> StalenessCheck:
    """as_of_date: ISO 'YYYY-MM-DD' (or full ISO datetime) the ruleset/scheme
    was pulled or last reviewed — NOT when the scan using it ran. An
    unparseable or empty date returns label="" (unknown), never a guessed
    current/stale — the same "say we couldn't read it, don't default to
    clean" rule security_summary.py's own `_age_days` follows."""
    if not as_of_date:
        return StalenessCheck("", None, threshold_days, as_of_date)
    try:
        parsed = datetime.fromisoformat(str(as_of_date).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return StalenessCheck("", None, threshold_days, as_of_date)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - parsed).days
    label = CURRENT if age <= threshold_days else STALE
    return StalenessCheck(label, age, threshold_days, as_of_date)
