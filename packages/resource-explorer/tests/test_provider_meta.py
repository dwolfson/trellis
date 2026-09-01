"""Tests for provider_meta.py — the general provider-provenance
abstraction (docs/gap-analyses-design.md §0b), built now, adopted later.
Standalone: no surveyor/registry involved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from resource_explorer.surveyors.sub_surveyors.provider_meta import (
    CURRENT,
    LIVE_QUERIED_API,
    RE_AUTHORED_SCHEME,
    STALE,
    VENDORED_RULESET,
    InvalidProvider,
    ProviderInfo,
    check_staleness,
)


class TestProviderInfoConstructorEnforcement:
    """Mirrors step_outcome.StepOutcome's constructor-enforced rule —
    malformed provenance is a silent lie unless caught at construction."""

    def test_valid_vendored_ruleset_record(self):
        p = ProviderInfo("gitleaks", VENDORED_RULESET, "abc123", "https://x.example")
        row = p.as_row()
        assert row == {
            "provider_name": "gitleaks", "provider_kind": VENDORED_RULESET,
            "version_or_as_of": "abc123", "source_url": "https://x.example",
        }

    def test_re_authored_scheme_may_have_empty_source_url(self):
        p = ProviderInfo("re_license_risk", RE_AUTHORED_SCHEME, "v1", "")
        assert p.source_url == ""

    def test_vendored_ruleset_with_empty_source_url_is_rejected_KNOWN_NEGATIVE(self):
        """Known-negative: only re_authored_scheme may skip source_url."""
        with pytest.raises(InvalidProvider):
            ProviderInfo("gitleaks", VENDORED_RULESET, "abc123", "")

    def test_live_api_with_empty_source_url_is_rejected(self):
        with pytest.raises(InvalidProvider):
            ProviderInfo("osv.dev", LIVE_QUERIED_API, "2026-09-01T00:00Z", "")

    def test_unknown_provider_kind_is_rejected(self):
        with pytest.raises(InvalidProvider):
            ProviderInfo("x", "not_a_real_kind", "v1", "https://x")

    def test_empty_provider_name_is_rejected(self):
        with pytest.raises(InvalidProvider):
            ProviderInfo("", VENDORED_RULESET, "v1", "https://x")

    def test_empty_version_is_rejected(self):
        with pytest.raises(InvalidProvider):
            ProviderInfo("gitleaks", VENDORED_RULESET, "", "https://x")


class TestGuardrailNoRenamedFields:
    """Design §0b's non-negotiable guardrail: as_row() must be additive
    fields only, never touching kind/check_name — this test pins the exact
    key set so a future edit that adds a 'kind' or 'check_name' key here
    (which would violate the guardrail) fails loudly."""

    def test_as_row_key_set_is_exactly_the_four_shared_fields(self):
        p = ProviderInfo("x", RE_AUTHORED_SCHEME, "v1")
        assert set(p.as_row().keys()) == {
            "provider_name", "provider_kind", "version_or_as_of", "source_url"}


class TestStaleness:
    def test_current_within_threshold(self):
        as_of = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
        result = check_staleness(as_of, threshold_days=30)
        assert result.label == CURRENT

    def test_stale_beyond_threshold(self):
        as_of = (datetime.now(timezone.utc) - timedelta(days=400)).date().isoformat()
        result = check_staleness(as_of, threshold_days=180)
        assert result.label == STALE

    def test_unparseable_date_is_unknown_not_current_KNOWN_NEGATIVE(self):
        """Known-negative: must not default an unreadable date to 'current'
        — that would be exactly the confident-clean-over-broken-input
        failure this whole design exists to prevent."""
        result = check_staleness("not-a-date", threshold_days=30)
        assert result.label == ""
        assert result.age_days is None

    def test_empty_date_is_unknown(self):
        result = check_staleness("", threshold_days=30)
        assert result.label == ""
