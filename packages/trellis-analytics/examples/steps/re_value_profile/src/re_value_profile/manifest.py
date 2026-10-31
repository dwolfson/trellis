"""The step's manifest: the wrapper's declaration. Its version is the package's."""
from trellis_analytics.declaration import (AbsenceSentences, BasisDeclaration, ConfidenceDeclaration, Declaration,
                                           ExtentDeclaration, ListDeclaration, MeasureDeclaration)
from trellis_analytics.manifest import StepManifest

from re_value_profile import __version__

MANIFEST = StepManifest(
    name="re_value_profile",
    display_name="Value Profile (RE spike twin)",
    function="re_value_profile.step.run",
    description=("What the columns of each table contain, from the latest value-profile batch Resource Explorer's "
                 "quality survey stored: per table its state, row count and columns measured, and per column the "
                 "value, distinct, null and filled counts. Opens no connection. A table or column that was not "
                 "profiled is shown as \"not measured\" with the reason, never as having no values."),
    returns="one ResourceMeasureAnnotation per table, and one summary for the database, each with its envelope",
    source="ods",
    version=__version__,
    resource_types=["database"],
    annotation_type="ResourceMeasureAnnotation",
    credential_tier="none",
    inputs=["ods"],
    measures=["re_value_profile", "re_value_profile_summary"],
    stage="analysis",
    perspectives=["Steward", "Data Expert"],
    questions=["Q-0079"],
    purposes=["Assess", "Learn"],
    family="Profile",
    tags=["profile", "values", "columns"],
    request_type="re-spike-value-profile",
    nothing_to_derive_guard="survey-completed",
    declaration=Declaration(
        result_kind="list",
        measures=[MeasureDeclaration(name="re_value_profile", unit="columns measured", as_of="asOf",
                                     value_field="Columns Measured",
                                     basis=BasisDeclaration(denominator_field="Columns", denominator_label="columns")),
                  MeasureDeclaration(name="re_value_profile_summary", unit="columns profiled", as_of="asOf",
                                     value_field="Columns Measured", scope="resource",
                                     basis=BasisDeclaration(denominator_field="Columns", denominator_label="columns"))],
        absence=AbsenceSentences(
            not_measured=("Not measured: no value profile is stored for this database, or this table was not "
                          "profiled (see its reason) — never shown as having no values."),
            not_permitted="Not permitted: the quality survey's account could not read this table.",
            not_applicable="Not applicable: a view or foreign table is not profiled.",
            measured_nothing="Measured: every profiled column is empty."),
        extents=[ExtentDeclaration(
            name="tables", fields=["scope", "Table State", "Record Count", "Columns", "Columns Measured"],
            rows=20, order="measured tables first, then tables not measured",
            truncation="{shown} of {total} tables shown", token_cost=600,
            citation="{analysis} · {scope} · as of {as_of}")],
        confidence=ConfidenceDeclaration(form="measured"),
        listing=ListDeclaration(item_fields=["scope", "Table State", "Columns Measured"],
                                order="measured tables first, then tables not measured", key_field="scope",
                                item_label="tables"),
        scope="container",
    ),
)
