"""The step's manifest: the wrapper's declaration. Its version is the package's."""
from trellis_analytics.manifest import StepManifest

from database_staleness import __version__

MANIFEST = StepManifest(
    name="database_staleness",
    display_name="Database Staleness",
    function="database_staleness.step.run",
    description=("Rows changed per table since the last survey: compares the latest two row-count snapshots "
                 "Resource Explorer stored for the database. Reads only what RE already stored; opens no "
                 "connection to the database."),
    returns="one ResourceMeasureAnnotation per table, each with its envelope",
    source="ods",
    version=__version__,
    resource_types=["database"],
    annotation_type="ResourceMeasureAnnotation",
    credential_tier="none",
    inputs=["ods"],
    stage="analysis",
    perspectives=["Steward", "Data Expert"],
    # Q-0041: "How much has changed since the last time this was surveyed — is it worth re-running now?"
    questions=["Q-0041"],
    purposes=["Maintain"],
    family="Freshness",
    tags=["staleness", "row counts"],
)
