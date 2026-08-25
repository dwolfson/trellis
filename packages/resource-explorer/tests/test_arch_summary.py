"""The summarising microflow — a step whose input is another step's output.

The behaviour that matters most here is the one that is easiest to get wrong:
an absent input must not become a confident summary of zero.
"""
from __future__ import annotations

import dataclasses

import pytest

from resource_explorer.surveyors import result_status as rs
from resource_explorer.surveyors.sub_surveyors import arch_summary as AS


class _Reg:
    def __init__(self, scopes=None, findings=None, raise_on_scopes=False):
        self._scopes, self._findings = scopes or [], findings or {}
        self._raise = raise_on_scopes

    def query_finding_scopes(self, slug, kind):
        if self._raise:
            raise RuntimeError("registry down")
        return list(self._scopes)

    def query_findings(self, slug, kind, scope=""):
        return list(self._findings.get(scope, []))


@dataclasses.dataclass
class _Proj:
    slug: str = "milvus"


def _run(reg):
    return AS.ArchSummarySurveyor(_Proj(), reg).run()


def _f(check, label="", detail=None):
    return {"check_name": check, "label": label, "detail": detail or {}}


def _port(protocol, operations=None, direction="Input-Output", name="api.proto"):
    """A port finding **exactly as `persist.py` writes one**.

    The detail carries `component`, `port`, `direction`, `protocol`,
    `additionalProperties` and `kind`. An earlier version of this helper carried
    only protocol and operationCount, so a test asserting on direction silently
    exercised the absent-direction path instead — the fifth time in this suite
    that a hand-written fake lagged the shape it stands for. Mirror the writer,
    not the fields the current test happens to read.
    """
    ap = {"operationCount": str(operations)} if operations is not None else {}
    return _f(f"port:{name}", direction,
              {"component": "svc", "port": name, "direction": direction,
               "protocol": protocol, "additionalProperties": ap, "kind": "port"})


class TestAnAbsentInputIsNotAnEmptySummary:
    """'Recovery has not run here' and 'recovery ran and found one component'
    are different statements about the repo. A summary reporting 0 collapses
    them — and unlike most absences it reads as a confident answer, which makes
    it harder to spot than any other instance of this failure in the codebase."""

    def test_no_source_findings_yields_not_established_not_a_zero(self):
        (ann,) = _run(_Reg(scopes=[]))
        status = ann.json_properties["result_status"]
        assert status["state"] == rs.NOT_ESTABLISHED
        assert "input step has not" in status["hint"]
        assert "0 component" not in ann.summary

    def test_the_status_names_which_step_it_depended_on(self):
        (ann,) = _run(_Reg(scopes=[]))
        assert ann.json_properties["result_status"]["cause"] == AS.SOURCE_KIND

    def test_an_unreadable_source_is_also_not_established(self):
        (ann,) = _run(_Reg(raise_on_scopes=True))
        assert ann.json_properties["result_status"]["state"] == rs.NOT_ESTABLISHED
        assert "could not be read" in ann.json_properties["result_status"]["hint"]


class TestTheTypeComesFromTheComponentFindingsLabel:
    """The first version counted `solutionComponentType = X` evidence rows and
    reported PROPOSERS as types — Milvus summarised as "167 go-subsystem, 16
    code marker". On a `component` finding the label IS the type; those other
    rows are the evidence for it."""

    def test_component_label_is_the_solution_component_type(self):
        reg = _Reg(scopes=["a", "b"], findings={
            "a": [_f("component", "Software Service"),
                  _f("solutionComponentType = Software Service", "deployment")],
            "b": [_f("component", "Long Running Daemon")]})
        (ann,) = _run(reg)
        t = ann.json_properties["component_types"]
        assert t == {"Software Service": 1, "Long Running Daemon": 1}
        assert "deployment" not in t, "a proposer was counted as a type"


class TestItSummarisesRatherThanRestates:
    def test_the_summary_does_not_lead_with_the_raw_component_count(self):
        """"204 components" is the raw analysis restated — and it is the number
        that made this step necessary."""
        reg = _Reg(scopes=[str(i) for i in range(20)],
                   findings={str(i): [_f("component", "Software Library")] for i in range(20)})
        (ann,) = _run(reg)
        assert not ann.summary.startswith("20 "), ann.summary
        assert "candidate component(s)" in ann.summary, (
            "the count is still reported, last and qualified — dropping it would "
            "hide the disagreement with an authors' own component count"
        )

    def test_suitability_leads_with_what_the_thing_serves(self):
        reg = _Reg(scopes=["a", "b"], findings={
            "a": [_f("component", "Software Service"), _port("gRPC", 296)],
            "b": [_f("component", "Software Library")]})
        (ann,) = _run(reg)
        assert ann.summary.startswith("serves gRPC (296 operations)"), ann.summary

    def test_the_ports_direction_label_is_not_mistaken_for_a_protocol(self):
        """A port finding's label is its DIRECTION. Reading it as the protocol
        reported "Input-Output" as something the component serves."""
        reg = _Reg(scopes=["a"], findings={
            "a": [_f("component", "Software Service"), _port("gRPC")]})
        (ann,) = _run(reg)
        assert "Input-Output" not in ann.summary
        assert ann.json_properties["protocols"] == {"gRPC": 1}

    def test_a_detail_stored_as_json_text_is_still_read(self):
        """query_findings may hand back detail as a JSON string."""
        import json as _j
        reg = _Reg(scopes=["a"], findings={"a": [
            _f("component", "Software Service"),
            _f("port:x", "Input-Output",
               _j.dumps({"protocol": "HTTP/REST",
                         "additionalProperties": {"operationCount": "40"}}))]})
        (ann,) = _run(reg)
        assert ann.json_properties["operations"] == 40

    def test_libraries_are_not_counted_as_runnable_units(self):
        """Software Library is the most-proposed type by far (163 of 218 on
        Milvus) and the least informative about runtime usability."""
        reg = _Reg(scopes=["a", "b"], findings={
            "a": [_f("component", "Software Library")],
            "b": [_f("component", "Long Running Daemon")]})
        (ann,) = _run(reg)
        assert "1 runnable unit(s)" in ann.summary

    def test_third_party_is_counted_separately(self):
        reg = _Reg(scopes=["a"], findings={"a": [_f("component", "Third Party Process")]})
        (ann,) = _run(reg)
        assert "1 third-party" in ann.summary
        assert ann.json_properties["third_party"] == 1


class TestItIsACheapStepByConstruction:
    def test_it_requires_no_external_resource(self):
        """No zipball, no clone — Discovery tier by rule 17's own test. A
        summary must be cheap enough to recompute whenever its inputs change."""
        assert AS.ArchSummarySurveyor.requires_resources == {}

    def test_depth_is_a_parameter_and_both_levels_are_implemented(self):
        """Depth is a request parameter in Egeria's model, not a new concept.
        Both declared levels now do something — `full` was retired rather than
        left declared-and-unbuilt, because a value nothing produces invites
        someone to pass it."""
        assert set(AS.DEPTHS) == {AS.DEPTH_SUITABILITY, AS.DEPTH_INTEGRATION}

    def test_an_unknown_depth_falls_back_rather_than_failing(self):
        s = AS.ArchSummarySurveyor(_Proj(), _Reg(scopes=[]), depth="nonsense")
        assert s._depth == AS.DEPTH_SUITABILITY


class TestTheStatusVocabularyWasReusedNotExtended:
    def test_dependency_not_satisfied_is_not_established_not_a_seventh_state(self):
        """The temptation was a `dependency_missing` state. The six describe
        what a READER is looking at, and that is 'we tried and could not tell';
        which upstream step was missing is a cause, and cause is the field."""
        st = rs.dependency_not_satisfied("x", depends_on="architecture_recovery")
        assert st["state"] == rs.NOT_ESTABLISHED
        assert st["cause"] == "architecture_recovery"
        assert not hasattr(rs, "DEPENDENCY_MISSING")


class TestItReadsBothKindsAndTheRightColumn:
    """Two things found only by running it against real data, each of which
    produced a plausible-looking wrong answer rather than an error."""

    def test_ports_are_read_from_the_interfaces_kind(self):
        """Ports persist under `architecture_interfaces`, whole-resource
        scoped — NOT alongside component findings. Reading one kind reported
        'serves nothing' while propose() was returning 31 ports for Milvus,
        and that is indistinguishable from a component with no interface."""
        assert AS.INTERFACE_KIND == "architecture_interfaces"
        assert AS.INTERFACE_KIND != AS.SOURCE_KIND

    def test_detail_is_read_from_detail_json(self):
        """`persist.py` passes `detail`; the registry column is `detail_json`.
        Reading `detail` got None on every row and silently produced no
        protocols and zero operations."""
        import json as _j

        class _R(_Reg):
            def query_findings(self, slug, kind, scope=""):
                if kind == AS.INTERFACE_KIND:
                    return [{"check_name": "port:api.proto", "label": "Input-Output",
                             "detail_json": _j.dumps({
                                 "protocol": "gRPC",
                                 "additionalProperties": {"operationCount": "296"}})}]
                return super().query_findings(slug, kind, scope)

        (ann,) = _run(_R(scopes=["a"],
                         findings={"a": [_f("component", "Software Service")]}))
        assert ann.json_properties["protocols"] == {"gRPC": 1}
        assert ann.json_properties["operations"] == 296


class TestIntegrationDepthAnswersHowWouldWeCallIt:
    """Depth is a summarisation level over the same analysis, not a second
    analysis. My own earlier note said this depth needed stage-two interface
    reads; that was true only of operation NAMES. Which components serve what,
    over which protocol, with how many operations, and what they call out to are
    all in `architecture_interfaces` already."""

    def _reg(self, ports):
        class _R(_Reg):
            def query_findings(self, slug, kind, scope=""):
                if kind == "architecture_interfaces":
                    return ports
                return super().query_findings(slug, kind, scope)
        return _R(scopes=["a"], findings={"a": [_f("component", "Software Service")]})

    def test_it_names_the_interface_not_the_owning_component(self):
        """An IDL port is named for the interface it defines; the component that
        owns it is whatever subtree the file sits in — `pkg` on Milvus, which
        tells a caller nothing. What you call is the interface."""
        reg = self._reg([_port("gRPC", 18)])
        (ann,) = AS.ArchSummarySurveyor(_Proj(), reg, depth=AS.DEPTH_INTEGRATION).run()
        assert "api.proto" in ann.summary
        assert "gRPC" in ann.summary

    def test_it_says_public_and_internal_are_not_distinguished(self):
        """Milvus declares 297 rpcs across ten .proto files. `proxy` is
        client-facing and the coord services are internal, and nothing in the
        code says so — reporting the largest surface would name `root_coord`
        (76 rpcs) over `proxy` (18) and be exactly backwards."""
        reg = self._reg([_port("gRPC", 18)])
        (ann,) = AS.ArchSummarySurveyor(_Proj(), reg, depth=AS.DEPTH_INTEGRATION).run()
        assert "not distinguished" in ann.summary
        assert "documentation" in ann.summary

    def test_no_served_interface_is_said_plainly(self):
        reg = self._reg([])
        (ann,) = AS.ArchSummarySurveyor(_Proj(), reg, depth=AS.DEPTH_INTEGRATION).run()
        assert "Nothing here serves an interface" in ann.summary

    def test_a_client_only_port_is_not_a_served_interface(self):
        """Direction is the whole point of §3.2's vocabulary: `Input-Output` is
        request-response PROVIDED, `Output-Input` is CALLED. Counting a client
        port as a served interface would invert the dependency."""
        reg = self._reg([_port("gRPC", 5, direction="Output-Input")])
        (ann,) = AS.ArchSummarySurveyor(_Proj(), reg, depth=AS.DEPTH_INTEGRATION).run()
        assert "Nothing here serves an interface" in ann.summary

    def test_suitability_is_unchanged_by_the_new_depth(self):
        reg = self._reg([_port("gRPC", 18)])
        (ann,) = AS.ArchSummarySurveyor(_Proj(), reg, depth=AS.DEPTH_SUITABILITY).run()
        assert "runnable unit" in ann.summary or "candidate component" in ann.summary


class TestFullWasRemovedRatherThanBuilt:
    """A summariser whose deepest level is *do not summarise* is describing the
    architecture-recovery results view, which already exists. Building it would
    have given a reader two spellings of one answer."""

    def test_full_is_gone_from_the_declared_depths(self):
        assert set(AS.DEPTHS) == {AS.DEPTH_SUITABILITY, AS.DEPTH_INTEGRATION}
        assert not hasattr(AS, "DEPTH_FULL"), (
            "a constant left behind invites someone to pass it"
        )

    def test_what_integration_still_cannot_say_is_named(self):
        """Operation names and signatures are deliberately not extracted
        (finding 100: a count is a summary, a listing is not), so their absence
        is a scoped decision rather than an oversight."""
        assert any("signature" in s for s in AS.INTEGRATION_NOT_ANSWERED)
        assert any("schema" in s for s in AS.INTEGRATION_NOT_ANSWERED)

    def test_the_retired_depth_falls_back_rather_than_erroring(self):
        """`full` was a declared value; anything that still asks for it should
        get the coarse answer, not a crash and not a silent 'full'."""
        s = AS.ArchSummarySurveyor(_Proj(), _Reg(scopes=[]), depth="full")
        assert s._depth == AS.DEPTH_SUITABILITY
