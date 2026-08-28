"""Bridge from RE's ingestion walk to the shared containment tree.

Off by default (`ARTIFACT_TREE_ENABLED`). Off means today's behaviour exactly:
this module opens no connection, creates no table, and does no work.

On, it builds a tree per file **in addition to** the chunks that walk already
produces. Not instead of: chunks are retrieval units sized by content profile,
tree nodes are containment units that compression rungs are cut from, and
neither derives from the other (docs/context-compilation-design.md §15). The two
come from the same walk over the same files, which is the point — one read, two
representations.

**Never breaks ingestion, and never lies about it.** A failure here does not
propagate -- a tree is an optimisation over a working pipeline and a broken one
must not cost the corpus -- but it is not swallowed into a success-shaped return
either. build_trees() hands back a TreeBuildResult carrying an explicit status,
so "the feature is off", "there was nothing to parse", "some files were skipped"
and "the store was unreachable" are four distinguishable outcomes rather than
four zeros. Returning a bare 0 for all of them is the exact shape
tests/test_no_silent_success.py ratchets against, and it was the first thing
this module got wrong.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_schema_ready = False


@dataclass(frozen=True)
class TreeBuildResult:
    """What actually happened, in a form a caller can branch on.

    status:
      "disabled"    -- feature off; nothing attempted, nothing wrong
      "stored"      -- every file parsed and persisted
      "partial"     -- some files skipped; `skipped` says how many
      "unavailable" -- setup failed; nothing stored, `reason` says why
    """

    status: str
    stored: int = 0
    skipped: int = 0
    reason: str = ""

    def __bool__(self) -> bool:
        return self.stored > 0


def _reset_for_tests() -> None:
    """Testing hook — the schema-created guard is process-global."""
    global _schema_ready
    _schema_ready = False


def _store():
    from trellis_artifact_tree import ArtifactTreeConfig, ArtifactTreeStore

    from resource_explorer.config import get_config

    cfg = get_config()
    pg = cfg.pgvector
    return ArtifactTreeStore(ArtifactTreeConfig(
        host=pg.host, port=pg.port, dbname=pg.dbname,
        # RE's PgVectorConfig deliberately avoids a bare `user` field (it would
        # collide with the shell's $USER under pydantic-settings); the shared
        # package's plain dataclass has no such problem, so translate here.
        user=pg.db_user, password=pg.password,
        schema=cfg.artifact_tree.schema_name,
    ))


def build_trees(
    files: list[tuple[str, str]],
    project_slug: str,
    kind: str = "markdown",
    source_version: str = "",
) -> TreeBuildResult:
    """Build and persist a tree per file.

    `files` is the (path, content) shape the pipeline's own walkers already
    yield, so callers pass what they have rather than re-reading anything.
    """
    from resource_explorer.config import get_config

    if not get_config().artifact_tree.enabled:
        return TreeBuildResult("disabled")

    global _schema_ready
    try:
        from trellis_artifact_tree import AdapterRegistry, Provenance

        store = _store()
        if not _schema_ready:
            store.create_schema()
            _schema_ready = True

        registry = AdapterRegistry()
        fetched_at = datetime.now(timezone.utc).isoformat()
        stored = skipped = 0
        for path, content in files:
            try:
                tree = registry.parse(
                    artifact_id=f"{project_slug}:{path}",
                    kind=kind,
                    source=content,
                    provenance=Provenance(
                        source_kind="repo",
                        source_id=path,
                        fetched_at=fetched_at,
                        # The commit the content came from, when the caller
                        # knows it. Without it a tree can be read back but not
                        # placed in time, which is what §10's as-of work needs.
                        source_version=source_version,
                    ),
                )
                store.put(tree)
                stored += 1
            except Exception:
                # One unparseable file must not abandon the rest -- but it is
                # counted, so a caller can tell a clean run from a lossy one.
                skipped += 1
                logger.warning("artifact tree: skipped %s", path, exc_info=True)
        return TreeBuildResult(
            status="partial" if skipped else "stored",
            stored=stored, skipped=skipped,
        )
    except Exception as exc:
        logger.warning(
            "artifact tree: unavailable for this run "
            "(ingestion continues with chunks)", exc_info=True,
        )
        return TreeBuildResult("unavailable", reason=f"{type(exc).__name__}: {exc}")
