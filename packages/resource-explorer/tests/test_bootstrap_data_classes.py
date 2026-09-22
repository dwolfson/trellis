"""Tests for `bootstrap_data_classes.py`'s existence check.

Live verification (2026-09-22) found the script's `get_guid_for_name` calls
checked their result with a bare `if not data_class_guid` — but pyegeria's
`get_guid_for_name` returns the literal string "No elements found" (not
None/""/an exception) on a miss. That string is truthy, so a miss read as
"already exists" and every create was silently skipped: a real run against
the live dev platform reported "Created Data Classes: 0, Skipped: 6" when
in fact nothing had ever been created. These tests pin the fix — routing the
lookup through `survey_definition_reader._as_guid`, which rejects the
sentinel because it contains whitespace, unlike a real GUID — with a
duck-typed fake pyegeria client rather than live Egeria.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.surveyors.database import bootstrap_data_classes as bdc

NO_ELEMENTS_FOUND = "No elements found"


class _FakeDesigner:
    """Duck-typed stand-in for pyegeria's DataDesigner.

    `existing_names` simulates DataClasses pyegeria already knows about;
    anything else looks up as the miss sentinel, exactly like a real miss.
    """

    def __init__(self, existing_names: set[str] | None = None):
        self.existing_names = existing_names or set()
        self.created: list[dict] = []
        self.linked: list[tuple[str, str]] = []

    def create_egeria_bearer_token(self, *_args, **_kwargs):
        return "fake-token"

    def get_guid_for_name(self, qualified_name):
        if qualified_name in self.existing_names:
            return f"guid-for-{qualified_name}"
        return NO_ELEMENTS_FOUND

    def create_data_class(self, body):
        qn = body["properties"]["qualifiedName"]
        self.created.append(body)
        self.existing_names.add(qn)
        return f"guid-for-{qn}"

    def link_data_class_definition(self, data_definition_guid, data_class_guid):
        self.linked.append((data_definition_guid, data_class_guid))


class _FakeReferenceDataManager:
    def __init__(self, existing_names: set[str] | None = None):
        self.existing_names = existing_names or set()
        self.created: list[dict] = []
        self.links: list[tuple[str, str]] = []

    def create_egeria_bearer_token(self, *_args, **_kwargs):
        return "fake-token"

    def get_guid_for_name(self, qualified_name):
        if qualified_name in self.existing_names:
            return f"guid-for-{qualified_name}"
        return NO_ELEMENTS_FOUND

    def create_valid_value_definition(self, body):
        qn = body["properties"]["qualifiedName"]
        self.created.append(body)
        self.existing_names.add(qn)
        return f"guid-for-{qn}"

    def link_valid_value_definition(self, vv_set_guid, vv_member_guid, **_kwargs):
        self.links.append((vv_set_guid, vv_member_guid))


@pytest.fixture(autouse=True)
def _egeria_env(monkeypatch):
    monkeypatch.setenv("EGERIA_PLATFORM_URL", "https://host.docker.internal:9443")
    monkeypatch.setenv("EGERIA_VIEW_SERVER", "qs-view-server")
    monkeypatch.setenv("EGERIA_USER", "erinoverview")
    monkeypatch.setenv("EGERIA_USER_PASSWORD", "secret")


def _run_bootstrap(designer, ref_manager):
    # bootstrap_data_classes.py imports DataDesigner/ReferenceDataManager
    # locally, inside bootstrap_data_classes(), so patching them on their
    # owning modules (rather than on bootstrap_data_classes itself) is what
    # actually intercepts the call.
    with patch("pyegeria.omvs.data_designer.DataDesigner", return_value=designer), patch(
        "pyegeria.omvs.reference_data.ReferenceDataManager", return_value=ref_manager,
    ):
        return bdc.bootstrap_data_classes()


class TestSentinelMissIsNotAnExistingElement:
    """A "No elements found" miss must be treated as absent, not present."""

    def test_all_six_data_classes_are_created_on_first_run(self):
        designer = _FakeDesigner()
        ref_manager = _FakeReferenceDataManager()

        rc = _run_bootstrap(designer, ref_manager)

        assert rc == 0
        created_names = {
            body["properties"]["qualifiedName"] for body in designer.created
        }
        assert created_names == {
            f"DataClass::{spec['name']}" for spec in bdc.STANDARD_DATA_CLASSES
        }
        # None of the six were mistaken for "already exists".
        assert len(designer.created) == len(bdc.STANDARD_DATA_CLASSES)

    def test_valid_value_sets_and_keywords_are_also_created(self):
        designer = _FakeDesigner()
        ref_manager = _FakeReferenceDataManager()

        _run_bootstrap(designer, ref_manager)

        created_names = {body["properties"]["qualifiedName"] for body in ref_manager.created}
        for spec in bdc.STANDARD_DATA_CLASSES:
            assert f"ValidValuesSet::{spec['name']}Keywords" in created_names
            for kw in spec["dataPatterns"]:
                assert f"ValidValueDefinition::{spec['name']}Keyword::{kw}" in created_names


class TestBodyShapesMatchWhatEgeriaActuallyAccepts:
    """Live verification (2026-09-22) found the sentinel fix alone was not
    enough to seed the platform: fixing the existence check just uncovered a
    second, real bug underneath it — `create_data_class`'s body omitted
    `properties.class`/`isOwnAnchor`, which Egeria rejects with a 400
    (`CLIENT_ERROR_400`), and `link_valid_value_definition` was called with no
    body at all, a gap `egeria_reference_catalog.py`'s own docstring already
    named ("makes pyegeria synthesise one and POST it un-serialised — a live
    bug this does not copy"). Both are fixed to match the body shapes
    `egeria_reference_catalog.py`'s `build_proposed_data_class_body`/
    `build_proposed_valid_value_set_body` already use correctly, verified
    end-to-end against the live dev platform (6/6 Data Classes created)."""

    def test_create_data_class_body_has_the_required_class_and_anchor_fields(self):
        designer = _FakeDesigner()
        ref_manager = _FakeReferenceDataManager()
        _run_bootstrap(designer, ref_manager)

        for body in designer.created:
            assert body["isOwnAnchor"] is True
            assert body["properties"]["class"] == "DataClassProperties"

    def test_valid_value_set_and_keyword_bodies_declare_isOwnAnchor(self):
        designer = _FakeDesigner()
        ref_manager = _FakeReferenceDataManager()
        _run_bootstrap(designer, ref_manager)

        for body in ref_manager.created:
            assert body["isOwnAnchor"] is True
            assert body["properties"]["class"] == "ValidValueDefinitionProperties"

    def test_linking_a_keyword_passes_an_explicit_relationship_body(self):
        # link_valid_value_definition(set_guid, member_guid, body=...) — a
        # missing `body` kwarg is exactly the bug being pinned here.
        # _FakeReferenceDataManager.link_valid_value_definition only records
        # (vv_set_guid, vv_member_guid) positionally and swallows kwargs, so
        # use a stricter fake that captures the body too.
        class _StrictRefManager(_FakeReferenceDataManager):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.link_bodies: list[dict | None] = []

            def link_valid_value_definition(self, vv_set_guid, vv_member_guid, body=None):
                self.link_bodies.append(body)
                return super().link_valid_value_definition(vv_set_guid, vv_member_guid, body=body)

        strict_ref = _StrictRefManager()
        _run_bootstrap(_FakeDesigner(), strict_ref)
        assert strict_ref.link_bodies
        for body in strict_ref.link_bodies:
            assert body is not None
            assert body["class"] == "NewRelationshipRequestBody"
            assert body["properties"]["class"] == "ValidValueMemberProperties"


class TestRealExistingElementsAreSkipped:
    """A real GUID (not the sentinel) must still short-circuit creation —
    the fix must not turn every run into an unconditional re-create."""

    def test_pre_existing_data_class_is_skipped_not_recreated(self):
        designer = _FakeDesigner(existing_names={"DataClass::EmailAddress"})
        ref_manager = _FakeReferenceDataManager()

        _run_bootstrap(designer, ref_manager)

        created_names = {body["properties"]["qualifiedName"] for body in designer.created}
        assert "DataClass::EmailAddress" not in created_names
        # The other five are still created normally.
        assert len(created_names) == len(bdc.STANDARD_DATA_CLASSES) - 1


class TestPreFixBehaviourWouldHaveSkippedEverything:
    """Documents the bug directly: the naive `if not guid` check treats the
    sentinel as truthy and would report every element as already existing."""

    def test_naive_truthiness_check_is_fooled_by_the_sentinel(self):
        designer = _FakeDesigner()
        guid = designer.get_guid_for_name("DataClass::EmailAddress")
        assert guid == NO_ELEMENTS_FOUND
        assert bool(guid) is True  # the bug: a miss reads as truthy
        assert bdc._as_guid(guid) is None  # the fix: rejected as not a real GUID
