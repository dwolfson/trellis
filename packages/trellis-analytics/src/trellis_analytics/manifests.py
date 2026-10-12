"""The manifests this package ships; each is an entry point in group `trellis.analytics`."""
from trellis_analytics import __version__
from trellis_analytics.manifest import RoutineManifest

CURATION_COVERAGE = RoutineManifest(
    name="curation_coverage",
    function="trellis_analytics.routines.curation_coverage.curation_coverage",
    description="Published, not yet published and blocked, counted from the curation record (analysis 1 of Curate's By analysis).",
    returns="CoverageResult (counts with the row ids they count, plus an Envelope)",
    source="ods",
    version=__version__,
    envelope=True,
    resource_types=["database"],
    family="Curation",
    tags=["curation", "coverage"],
)
