"""Fields a reader promises must exist in rows that were actually stored.

The presentation session's generalisation, after finding that
`_architecture_doc_lens_results`' docstring asserted `evidence_kind` "is carried
per component" while **212 stored rows across 11 repos carried none of it**. It
was computed in `architecture_doc.py` and dropped at the persistence boundary.

The failure is invisible from either side: the computing code is correct, the
docstring describes the intent correctly, and the reader returns what it finds.
Only a question nobody asks — *is it actually in a row?* — reveals it. That is
the same family as a test agreeing with its subject while the caller disagrees,
and as a summary that computes and stores nothing: **each part reads correct on
its own.**

These run against the live registry and skip when it is empty, deliberately.
A fixture would assert what we constructed, which is what the docstring already
did.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import ProjectRegistry

#: kind -> check_name -> fields a reader or its docstring promises are present.
PROMISED_DETAIL_FIELDS = {
    "architecture_doc_lens": {
        "documented_by": ("term", "evidence", "evidence_kind"),
    },
    "architecture_summary": {
        "architecture_summary": ("depth", "components", "documented"),
    },
}

#: The reader for each kind, because the contract is about what a reader
#: SURFACES — that is what a renderer sees, and it is where the promise was
#: made. Asserting on raw rows instead conflates two different failures: a
#: field the persistence never wrote (a bug), and a row left behind by an
#: earlier run of code that predates the field (history). Three such rows
#: survived a full corpus refresh on `docling_eval` and `docling_java`, because
#: nothing removes a finding that is no longer produced — and the reader's job
#: includes not presenting those as current.
READERS = {
    "architecture_doc_lens": ("_architecture_doc_lens_results", "findings"),
    "architecture_summary": ("_architecture_summary_results", None),
}


def _detail(row):
    d = row.get("detail_json") or row.get("detail") or {}
    if isinstance(d, str):
        try:
            return json.loads(d)
        except Exception:
            return {}
    return d if isinstance(d, dict) else {}


@pytest.fixture(scope="module")
def registry():
    try:
        return ProjectRegistry()
    except Exception:  # noqa: BLE001
        pytest.skip("registry unavailable")


@pytest.mark.parametrize("kind,checks", PROMISED_DETAIL_FIELDS.items())
def test_promised_fields_reach_a_reader(registry, kind, checks):
    """Through the reader, against live data."""
    import importlib

    adapter = importlib.import_module(
        "resource_explorer.surveyors.repo_survey_definition_adapter")
    fn_name, list_key = READERS[kind]
    reader = getattr(adapter, fn_name)
    promised = next(iter(checks.values()))

    seen = 0
    for p in registry.list_all():
        result = reader(registry, p.slug)
        if result.get("state"):
            continue                       # never run for this resource
        items = result.get(list_key, []) if list_key else [result]
        for item in items:
            seen += 1
            missing = [f for f in promised if f not in item or item[f] == ""]
            assert not missing, (
                f"{kind} on {p.slug} reaches a reader missing {missing} — the "
                f"promise is in the reader's docstring and the data does not "
                f"keep it. Fix the persistence, not the docstring."
            )
    if not seen:
        pytest.skip(f"no {kind} results yet — nothing to check against")


def test_evidence_kind_is_one_of_the_declared_values(registry):
    """A field that is present but carries anything is not much better than
    absent. `kind` sits beside it holding the constant "doc-lens", and the two
    names are close enough that one was mistaken for the other."""
    from resource_explorer.github.architecture_doc import (
        EVIDENCE_EMPHASISED,
        EVIDENCE_MENTIONED,
    )

    import importlib

    adapter = importlib.import_module(
        "resource_explorer.surveyors.repo_survey_definition_adapter")
    valid, seen = {EVIDENCE_EMPHASISED, EVIDENCE_MENTIONED}, 0
    for p in registry.list_all():
        result = adapter._architecture_doc_lens_results(registry, p.slug)
        for item in result.get("findings", []):
            seen += 1
            assert item.get("evidence_kind") in valid, (
                f"{p.slug}/{item.get('component')}: "
                f"evidence_kind={item.get('evidence_kind')!r}")
    if not seen:
        pytest.skip("no doc-lens rows stored yet")
