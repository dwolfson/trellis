"""Create Egeria ValidValueDefinition/ValidValueSet "measure" catalogs —
the externalized, citable interpretation rules a Question's answer should
follow, per docs/survey-question-context-plan.md's follow-up discussion
(2026-08-13): "what information is needed to answer each Question... and
how do we interpret it consistently" maps directly onto Egeria's own
Reference Data types (https://egeria-project.org/types/5/0545-Reference-Data/)
— ValidValueDefinition/ValidValueSet + ValidValueMember, not a new
RE-local file format.

Why a Python script and not a Dr.Egeria markdown doc (the pattern used
everywhere else in this codebase, e.g. generate_repo_survey_definition.py):
confirmed live (2026-08-13) that no "Create Valid Value (Definition|Set)"/
"Link Valid Value Member" Dr.Egeria command exists yet in egeria-python's
compact command specs — only the underlying pyegeria SDK methods
(ReferenceDataManager.create_valid_value_definition/link_valid_value_definition)
are real and dedicated. Once those Dr.Egeria commands are authored (a real,
separate follow-up — flagged, not attempted here), this script's job moves
to a markdown doc + mcp__egeria__dr_egeria_run_block, matching every other
repeatable-authoring artifact in docs/dr-egeria/. Until then, this script
IS the repeatable mechanism — idempotent (find-or-create, safe to re-run
against any Egeria instance), same spirit as the *.md docs it'll eventually
be replaced by.

ValidValuesAssignment (Question-to-measure-set) and ReferenceValueAssignment
(tagging an actual result with its resolved value) pyegeria methods now
exist (pyegeria>=6.0.18.1 — see egeria-python's PYEGERIA_ISSUES.md
ISSUE-56) but are still NOT wired up here — using them is a real, separate
follow-up (they'd replace the ScopedBy substitute mentioned below for
Question-to-measure-set linking specifically), not attempted in this pass.
ScopedBy is still used as the interim substitute for linking a Question to
its measure set (see link_measure_set_to_question()), matching the
"Survey Definition -> Question" ScopedBy precedent this session already
proved out (dr_egeria_survey_publisher.py / D1).

ValidValueMember linking (measure set -> its member values, this script's
own _link_member()) previously failed on every call — pyegeria's
link_valid_value_definition() validated the request body against the wrong
Pydantic model (NewElementRequestBody instead of NewRelationshipRequestBody,
both share the "class" field name but different Literal values), so a body
built exactly per the method's own documented sample always failed
validation. Filed as ISSUE-56 (egeria-python/PYEGERIA_ISSUES.md) and fixed
upstream in pyegeria 6.0.18.1 (2026-08-15) — confirmed live: all 3
measure-set members link successfully now, and re-running the script is
idempotent (find-or-create skips existing elements, re-linking an existing
member doesn't error).

Usage:
    uv run python scripts/create_measure_definitions.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging

log = logging.getLogger(__name__)

_DEFAULT_PLATFORM_URL = "https://localhost:9443"
_DEFAULT_VIEW_SERVER = "qs-view-server"
_DEFAULT_USER_ID = "erinoverview"
_DEFAULT_USER_PASSWORD = "secret"


def _connect(platform_url, view_server, user_id, user_password):
    from pyegeria.omvs.reference_data import ReferenceDataManager

    client = ReferenceDataManager(view_server, platform_url, user_id, user_password)
    client.create_egeria_bearer_token(user_id, user_password)
    return client


def _connect_classification_explorer(platform_url, view_server, user_id, user_password):
    from pyegeria.omvs.classification_explorer import ClassificationExplorer

    client = ClassificationExplorer(view_server, platform_url, user_id, user_password)
    client.create_egeria_bearer_token(user_id, user_password)
    return client


def _find_by_name(ce_client, name: str, type_name: str = "ValidValueDefinition") -> str | None:
    """Find-by-displayName — real gap confirmed live (2026-08-13):
    ReferenceDataManager.find_valid_value_definitions()/
    get_valid_value_definitions_by_name() do NOT reliably surface a
    just-created ValidValueDefinition (confirmed: a set created and
    confirmed to exist via a 409 "qualifiedName already in use" on a
    second create attempt was invisible to both of those methods, even
    with a wildcard "*" search). ClassificationExplorer.get_guid_for_name()
    — the same generic lookup this codebase already uses for Question
    GlossaryTerms — finds it reliably instead, so that's what this uses.
    Worth flagging to whoever's already touching pyegeria for the 3
    missing Reference Data relationship methods (docs/survey-question-
    context-plan.md's follow-up) — this is a second, separate real gap
    in the same client.

    type_name defaults to ValidValueDefinition (this script's original use)
    but is generic — also used to resolve a Question's GlossaryTerm GUID
    for link_measure_set_to_question() below, matching
    survey_definition_reader.py's resolve_question_guid() exactly (same
    call shape, not duplicated logic, just not importable here since this
    script deliberately has no resource_explorer app dependency)."""
    try:
        result = ce_client.get_guid_for_name(name, property_name=["displayName"], type_name=type_name)
    except Exception as exc:
        log.debug("get_guid_for_name(%r, type_name=%r) failed: %s", name, type_name, exc)
        return None
    # pyegeria returns a bare string (e.g. "No elements found") instead of
    # None/[] on a miss — the same quirk survey_definition_reader.py already
    # guards against. A real GUID is never a sentence, but check length too
    # so this doesn't accidentally accept some other short string result.
    if not result or not isinstance(result, str) or " " in result:
        return None
    return result


def link_measure_set_to_question(ce_client, set_guid: str, set_display_name: str,
                                  question_display_name: str, dry_run=False) -> None:
    """D1's ScopedBy substitute (docs/survey-question-context-plan.md),
    for the measure-set -> Question direction — same mechanism and same
    element/scope roles as the already-proven "Survey Definition -> Question"
    ScopedBy link (dr_egeria_survey_publisher.py's render_scope_link_block(),
    backed by egeria-python's CurationLinkProcessor: ScopedBy's
    "Target Element" is the scoped element, "Scope Reference" is the scope
    — here, the measure set is the Target Element, the Question is the
    Scope Reference). Deferred until ISSUE-56 (ValidValueMember linking)
    was fixed, so the set was a coherent hierarchy before anything pointed
    at it — that's done now (see script docstring), this is the follow-up.

    Idempotent: checks the set's existing scopes via get_scopes() before
    linking, so re-running the script doesn't error on an already-linked
    Question (ScopedBy has no documented duplicate-link guard of its own,
    unlike ValidValueDefinition's create-time 409 — safer to check first
    than to find out live)."""
    question_guid = _find_by_name(ce_client, question_display_name, type_name="GlossaryTerm")
    if not question_guid:
        print(f"  ⚠ Question '{question_display_name}' not found (GlossaryTerm lookup failed) — "
              "skipping ScopedBy link. Has it been authored yet (docs/dr-egeria/resource_questions.csv)?")
        return

    if dry_run:
        print(f"  [dry-run] would link '{set_display_name}' -> Question '{question_display_name}' (ScopedBy)")
        return

    try:
        existing_scopes = ce_client.get_scopes(set_guid, page_size=1000)
    except Exception as exc:
        log.debug("get_scopes(%r) failed: %s", set_guid, exc)
        existing_scopes = None
    if isinstance(existing_scopes, list):
        already_linked = any(
            (el.get("elementHeader", {}) or {}).get("guid") == question_guid
            for el in existing_scopes
        )
        if already_linked:
            print(f"  '{set_display_name}' already ScopedBy '{question_display_name}' — not re-linking")
            return

    body = {"class": "NewRelationshipRequestBody", "properties": {"class": "ScopedByProperties"}}
    ce_client.add_scope_to_element(scoped_by_guid=question_guid, element_guid=set_guid, body=body)
    print(f"  linked '{set_display_name}' -> Question '{question_display_name}' (ScopedBy)")


def _create_valid_value(client, ce_client, *, qualified_name, display_name, description,
                         usage, preferred_value, scope="", namespace_path="",
                         is_own_anchor=True, dry_run=False) -> str | None:
    existing_guid = _find_by_name(ce_client, display_name)
    if existing_guid:
        print(f"  found existing '{display_name}' (guid={existing_guid}) — not re-creating")
        return existing_guid

    body = {
        "class": "NewElementRequestBody",
        "isOwnAnchor": is_own_anchor,
        "properties": {
            "class": "ValidValueDefinitionProperties",
            "qualifiedName": qualified_name,
            "displayName": display_name,
            "description": description,
            "namespacePath": namespace_path,
            "usage": usage,
            "dataType": "string",
            "scope": scope,
            "preferredValue": preferred_value,
            "isCaseSensitive": False,
        },
    }
    if dry_run:
        print(f"  [dry-run] would create '{display_name}' ({qualified_name})")
        return None

    guid = client.create_valid_value_definition(body)
    print(f"  created '{display_name}' (guid={guid})")
    return guid


def _link_member(client, set_guid: str, member_guid: str, *, is_default: bool, label: str, dry_run=False) -> None:
    if dry_run or not set_guid or not member_guid:
        print(f"  [dry-run] would link member guid={member_guid} -> set guid={set_guid}")
        return
    body = {
        "class": "NewRelationshipRequestBody",
        "properties": {
            "class": "ValidValueMemberProperties",
            "isDefaultValue": is_default,
            "label": label,
            "description": "",
        },
    }
    client.link_valid_value_definition(set_guid, member_guid, body)
    print(f"  linked member guid={member_guid} -> set guid={set_guid}")


# ── Repository Maintenance Activity — the pilot measure set ─────────────────
# Discretizes OpenSSF Scorecard's real, continuous "Maintained" check
# (https://github.com/ossf/scorecard/blob/main/docs/checks.md) into 3
# labeled tiers for our own use — the discretization boundaries are RE's
# own choice, not something Scorecard itself hands down as fixed labels
# (Scorecard scores 0-10, not 3 discrete tiers); the underlying criteria
# quoted in each member's "usage" field ARE the cited Scorecard rule,
# verbatim in spirit, not invented.
_MEASURE_SETS = [
    {
        "qualified_name": "ValidValueSet::RepositoryMaintenanceActivity",
        "display_name": "Repository Maintenance Activity",
        "description": (
            "Interpretation set for 'Is this repository actively maintained?' "
            "(docs/dr-egeria/resource_questions.csv) — 3 tiers discretized from "
            "OpenSSF Scorecard's Maintained check, a real external standard, "
            "not an RE-invented threshold."
        ),
        "usage": "Answers the Question 'Is this repository actively maintained?'",
        "answers_question": "Is this repository actively maintained?",
        "scope": "Git Repository",
        "namespace_path": "resource-explorer.measures.repository",
        "members": [
            {
                "qualified_name": "ValidValue::RepositoryMaintenanceActivity::ActivelyMaintained",
                "display_name": "Actively Maintained",
                "description": "At least one commit per week over the trailing 90 days.",
                "usage": (
                    "OpenSSF Scorecard Maintained check, highest tier: >=1 commit/week "
                    "over the trailing 90 days. Source: "
                    "https://github.com/ossf/scorecard/blob/main/docs/checks.md"
                ),
                "preferred_value": "actively_maintained",
                "is_default": True,
            },
            {
                "qualified_name": "ValidValue::RepositoryMaintenanceActivity::PartiallyMaintained",
                "display_name": "Partially Maintained",
                "description": "No qualifying commit cadence, but issue activity from a collaborator/member/owner in the trailing 90 days.",
                "usage": (
                    "OpenSSF Scorecard Maintained check, partial tier: issue activity "
                    "(comments/closes) from collaborators, members, or owners within the "
                    "trailing 90 days, without the commit-cadence threshold being met. "
                    "Source: https://github.com/ossf/scorecard/blob/main/docs/checks.md"
                ),
                "preferred_value": "partially_maintained",
                "is_default": False,
            },
            {
                "qualified_name": "ValidValue::RepositoryMaintenanceActivity::NotMaintained",
                "display_name": "Not Maintained",
                "description": "Archived, or no commit/issue activity in the trailing 90 days.",
                "usage": (
                    "OpenSSF Scorecard Maintained check, lowest tier: repository is "
                    "archived, or shows neither qualifying commit cadence nor issue "
                    "activity in the trailing 90 days. Also the only tier assignable to "
                    "a repository under 90 days old (Scorecard's own check requires "
                    ">90 days of history to evaluate at all). "
                    "Source: https://github.com/ossf/scorecard/blob/main/docs/checks.md"
                ),
                "preferred_value": "not_maintained",
                "is_default": False,
            },
        ],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--platform-url", default=_DEFAULT_PLATFORM_URL)
    parser.add_argument("--view-server", default=_DEFAULT_VIEW_SERVER)
    parser.add_argument("--user-id", default=_DEFAULT_USER_ID)
    parser.add_argument("--user-password", default=_DEFAULT_USER_PASSWORD)
    args = parser.parse_args()

    client = _connect(args.platform_url, args.view_server, args.user_id, args.user_password)
    ce_client = _connect_classification_explorer(args.platform_url, args.view_server, args.user_id, args.user_password)

    for spec in _MEASURE_SETS:
        print(f"[{spec['display_name']}]")
        set_guid = _create_valid_value(
            client, ce_client,
            qualified_name=spec["qualified_name"],
            display_name=spec["display_name"],
            description=spec["description"],
            usage=spec["usage"],
            preferred_value=spec["display_name"],
            scope=spec["scope"],
            namespace_path=spec["namespace_path"],
            dry_run=args.dry_run,
        )
        for member in spec["members"]:
            # Each member is created as its own standalone, self-anchored
            # element (isOwnAnchor=True, same as the set) — the
            # ValidValueMember hierarchy relationship is added afterward via
            # a separate link_valid_value_definition() call rather than at
            # creation time (parentGUID/parentRelationshipTypeName), since
            # only the separate two-call shape is demonstrated in
            # create_valid_value_definition()'s own docstring — not
            # guessing at the combined create-and-link body shape.
            member_guid = _create_valid_value(
                client, ce_client,
                qualified_name=member["qualified_name"],
                display_name=member["display_name"],
                description=member["description"],
                usage=member["usage"],
                preferred_value=member["preferred_value"],
                dry_run=args.dry_run,
            )
            try:
                _link_member(
                    client, set_guid, member_guid,
                    is_default=member["is_default"], label=member["display_name"],
                    dry_run=args.dry_run,
                )
            except Exception as exc:
                # link_valid_value_definition() used to always fail here
                # (ISSUE-56, egeria-python's PYEGERIA_ISSUES.md — fixed in
                # pyegeria 6.0.18.1, confirmed live 2026-08-15). This
                # try/except is now just ordinary resilience against a
                # single member's link genuinely failing for some other
                # reason — report and continue rather than abort the whole
                # run, since the ValidValueDefinition elements themselves
                # (the actually valuable, citable part) are unaffected
                # either way.
                print(f"  ⚠ link failed: {exc}")

        answers_question = spec.get("answers_question")
        if answers_question:
            link_measure_set_to_question(
                ce_client, set_guid, spec["display_name"], answers_question,
                dry_run=args.dry_run,
            )


if __name__ == "__main__":
    main()
