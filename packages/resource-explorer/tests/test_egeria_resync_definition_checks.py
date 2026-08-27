"""Two checks that were one until 2026-08-26.

`_scan_definition_drift` compared Egeria against the CSV and called Egeria
"behind". That silently assumed the CSV was authoritative and that every
definition should have a CSV row — so an Egeria-native survey, or one authored
directly, would have been reported as drift. It did not, only because none
existed yet.

    recovery   docs ↔ Egeria   tolerates nothing, drives the repair
    coverage   CSV ↔ docs      tolerates extra definitions, no repair

The CSV is a specification of what surveys are NEEDED. The documents are the
definitions, and carry ordering, guards and descriptions the CSV has no column
for.
"""
from pathlib import Path

from resource_explorer import egeria_resync as R
from resource_explorer.surveyors import survey_definition_docs as D

DOCS = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "survey-definitions"


# ── the document parser ─────────────────────────────────────────────────────
def test_parses_steps_in_declared_order_ignoring_the_link_section(tmp_path):
    """Every step name appears three more times in the Link commands. Counting
    those would triple each step and make the parse depend on the link
    structure — the very thing that breaks and needs detecting."""
    doc = tmp_path / "d.md"
    doc.write_text(
        "## Create Governance Action Process Step\n"
        "### Qualified Name\nGovActionProcessStep::S::step_b\n\n"
        "### Description\nSecond, declared first.\n\n___\n\n"
        "## Create Governance Action Process Step\n"
        "### Qualified Name\nGovActionProcessStep::S::step_a\n\n"
        "### Description\nFirst.\n\n___\n\n"
        "## Create Governance Action Process\n"
        "### Qualified Name\nGovActionProcess::S\n\n___\n\n"
        "## Link Next Process Step\n"
        "### Governance Action Process Step\nGovActionProcessStep::S::step_b\n\n"
        "### Next Governance Action Process Step\nGovActionProcessStep::S::step_a\n"
    )
    parsed = D.parse_document(doc)
    assert parsed.process == "S"
    assert parsed.steps == ["step_b", "step_a"]   # declaration order, not sorted
    assert parsed.descriptions["step_b"] == "Second, declared first."
    # Links are read from the Link commands, never inferred from step order.
    assert parsed.links == [("step_b", "step_a", "Any")]


def test_a_description_cannot_be_borrowed_from_the_next_command(tmp_path):
    """A step with no Description must report none, not inherit its
    neighbour's — which would attribute one step's meaning to another."""
    doc = tmp_path / "d.md"
    doc.write_text(
        "## Create Governance Action Process Step\n"
        "### Qualified Name\nGovActionProcessStep::S::bare\n\n___\n\n"
        "## Create Governance Action Process Step\n"
        "### Qualified Name\nGovActionProcessStep::S::described\n\n"
        "### Description\nBelongs to `described`.\n\n___\n\n"
        "## Create Governance Action Process\n"
        "### Qualified Name\nGovActionProcess::S\n"
    )
    parsed = D.parse_document(doc)
    assert parsed.descriptions["bare"] == ""
    assert parsed.descriptions["described"] == "Belongs to `described`."


def test_an_unreadable_document_yields_nothing_rather_than_raising(tmp_path):
    parsed = D.parse_document(tmp_path / "absent.md")
    assert parsed.process == "" and parsed.steps == [] and parsed.links == []


def test_the_process_heading_does_not_swallow_the_step_heading(tmp_path):
    """"## Create Governance Action Process" is a prefix of the step heading.
    Matched loosely, every step would register as the process."""
    doc = tmp_path / "d.md"
    doc.write_text(
        "## Create Governance Action Process Step\n"
        "### Qualified Name\nGovActionProcessStep::S::only\n\n___\n\n"
        "## Create Governance Action Process\n"
        "### Qualified Name\nGovActionProcess::S\n"
    )
    parsed = D.parse_document(doc)
    assert parsed.process == "S" and parsed.steps == ["only"]


# ── the real documents ──────────────────────────────────────────────────────
def test_every_committed_document_parses_to_a_named_definition():
    """A document that parses to nothing is invisible to the recovery check,
    which would report its definition as somebody else's and never repair it."""
    for path in sorted(DOCS.glob("*.md")):
        parsed = D.parse_document(path)
        assert parsed.process, f"{path.name} declares no GovActionProcess"
        assert parsed.steps, f"{path.name} declares no steps"
        assert len(parsed.links) == len(parsed.steps) - 1, (
            f"{path.name}: {len(parsed.links)} link(s) for "
            f"{len(parsed.steps)} step(s) — a linear chain has exactly one fewer")


def test_the_csv_specifies_nothing_the_documents_do_not_define():
    """The coverage check against real data. A gap here means a step can never
    reach Egeria however often the repair runs — nothing authored it."""
    documented = R._documented_definitions()
    for name, want in R._intended_steps_from_csv().items():
        entry = documented.get(name)
        assert entry, f"CSV specifies {name}, no document defines it"
        missing = [k for k in want if k not in entry["steps"]]
        assert not missing, f"{name} document is behind the CSV: {missing}"


def test_coverage_tolerates_a_document_with_no_csv_row():
    """The CSV is not required to be complete — that is what makes it a
    specification of what is needed rather than a definition of what exists.
    Egeria-native surveys have no CSV row by nature."""
    documented = R._documented_definitions()
    specified = R._intended_steps_from_csv()
    extra = set(documented) - set(specified)
    gaps = R.EgeriaResync.__dict__["_scan_specification_gap"](
        object.__new__(R.EgeriaResync))
    assert not [g for g in gaps.items if g["definition"] in extra]


def test_the_coverage_finding_offers_no_repair_button():
    """Closing a coverage gap edits the source tree, and the generator may
    rightly refuse if a document was hand-authored since. This panel repairs
    the catalog, not the repository."""
    finding = R.EgeriaResync.__dict__["_scan_specification_gap"](
        object.__new__(R.EgeriaResync))
    assert finding.repair_step == ""
    assert finding.needs_decision is True


# ── needs_republish: two causes, not one ────────────────────────────────────
def test_never_catalogued_is_not_reported_as_a_lost_asset(pg_registry):
    """The finding claimed every member was "previously catalogued that Egeria
    no longer holds". Measured 2026-08-27: of seven, three had only a scout
    import and were never catalogued at all.

    Telling someone they lost something they never had sends them hunting a
    fault that does not exist, and the two need different actions — restoring a
    known asset versus a first publish.
    """
    from resource_explorer.registry import Project

    registry = pg_registry
    for slug in ("was_published", "never_published"):
        registry.add(Project(slug=slug, display_name=slug,
                             github_url=f"https://github.com/x/{slug}"))
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO entity_egeria_project_context "
                "(entity_type, entity_slug, status) VALUES (?,?,?)",
                ("repo", slug, "linked"),
            )
    # Only one of them has a completed catalog operation behind it. Written
    # through the real logging API rather than raw SQL, so the row is shaped
    # exactly as a genuine publish would leave it.
    from resource_explorer.activity_logger import log_catalog

    log_catalog(registry, "repo", "was_published", "was_published", "",
                "ok", "Published to Egeria")

    scanner = object.__new__(R.EgeriaResync)
    scanner._registry = registry
    finding = R.EgeriaResync.__dict__["_scan_unpublished_but_expected"](scanner)

    by_slug = {i["slug"]: i for i in finding.items}
    assert by_slug["was_published"]["was_published"] is True
    assert "asset lost" in by_slug["was_published"]["cause"]
    assert by_slug["never_published"]["was_published"] is False
    assert "never catalogued" in by_slug["never_published"]["cause"]
    # The title must not assert loss for the ones that never had an asset.
    assert "1 lost an asset, 1 never had one" in finding.title
