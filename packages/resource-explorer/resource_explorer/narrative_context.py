"""A file system's narrative passages, as one section of a chat compile (Files follow-up 1, the reader half of F11).

`narrative_docs` presses each narrative file (README, codebook, data dictionary) into `fs_<slug>_narratives`. This is
what a chat question scoped to that file system reads back: the top passages for the question, packed within the
compile's own budget and cited as `stated by <path> § <section>`, each a proposal, never a measured fact.

Three states, each in its own words, because "no narratives" is a claim this never makes:

* `not_read`   the file system was never pressed: "not read yet" (the screen's word, `narrative_docs.view`);
* `no_match`   it was pressed and no passage matched the question: the files may say it in other words;
* `unavailable` the search index could not be reached: said as a failure, never as an absence.

Rows written before the stated_by change carry a bare file name; they are cited as they hold it, with the metadata's
`file_path` added when present. Nothing is re-pressed here and nothing is written.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from trellis_artifact_tree.model import Rung

log = logging.getLogger(__name__)

SECTION_KEY = "narratives"
#: Passages searched for one question: the packer's budget decides how many words of them reach the model.
TOP_K = 5
FULL_CLIP = 900
SUMMARY_CLIP = 160
PROPOSAL = "proposal"
LABEL = "a proposal: what the file says, not a measured fact"

NOT_READ_WORDS = "not read yet"
NOT_READ = (f"Narrative files of this file system: {NOT_READ_WORDS}. Its README and notes have not been pressed into "
            "the search index, so this says nothing about what they contain.")
NO_MATCH = ("Narrative files of this file system: read, and no passage matched this question. The files may still say "
            "it in other words; do not tell the person there are no narratives.")
UNAVAILABLE = ("Narrative files of this file system: the search index could not be reached, so they were not "
               "searched. This is not a finding about the files.")


def citation(meta: dict) -> str:
    """`stated by <path> § <section>`: whatever stated_by the row holds, and for a row from an old press (a bare file
    name) the metadata's file_path as well, when it is not already in it."""
    stated = (meta.get("stated_by") or "").strip()
    path = (meta.get("file_path") or "").strip()
    if not stated:
        stated = path
        if path and meta.get("section"):
            from resource_explorer.surveyors.filesystem.narrative_docs import stated_by_of
            stated = stated_by_of(path, meta["section"])
    elif path and path not in stated:
        stated = f"{stated} ({path})"
    return f"stated by {stated}"


def passage_of(result) -> dict:
    meta = result.metadata or {}
    walk_run, path, section = meta.get("walk_run") or "", meta.get("file_path") or "", meta.get("section") or ""
    pid = ""
    if walk_run and path:
        from resource_explorer.surveyors.filesystem.narrative_docs import passage_id
        pid = passage_id(walk_run, path, section)
    return {"passage_id": pid, "walk_run": walk_run, "file_path": path, "section": section,
            "stated_by": meta.get("stated_by") or "", "status": PROPOSAL, "citation": citation(meta),
            "score": round(float(getattr(result, "score", 0.0) or 0.0), 3), "text": result.text or ""}


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def _rungs(passages: list[dict]) -> dict[Rung, str]:
    head = f"Narrative passages ({LABEL}); cite one as written:"
    full = [head] + [f"- [{p['citation']} — {PROPOSAL}] {_clip(p['text'], FULL_CLIP)}" for p in passages]
    summary = [head] + [f"- [{p['citation']} — {PROPOSAL}] {_clip(p['text'], SUMMARY_CLIP)}" for p in passages]
    ids = [f"Narrative passages ({PROPOSAL}), text left out to fit the budget:"] + \
          [f"- {p['citation']} — {PROPOSAL}" for p in passages]
    return {Rung.FULL: "\n".join(full), Rung.SUMMARY: "\n".join(summary), Rung.IDENTIFIERS: "\n".join(ids)}


def build(registry, slug: str, question: str, *,
          store_factory: Callable[[], object] | None = None) -> tuple[dict[Rung, str], dict]:
    """(rungs, info) for the narratives section. `info` = {"state", "passages", "collection"}; the rungs always say
    something, so the section is never silent."""
    from resource_explorer.surveyors.filesystem import narrative_docs as nd

    try:
        pressed = bool(registry.query_step_runs(slug=slug, step_key=nd.STEP_KEY, entity_type="filesystem", limit=1))
    except Exception:
        log.warning("narrative run of %s could not be read", slug, exc_info=True)
        return {r: UNAVAILABLE for r in Rung}, {"state": "unavailable", "passages": [], "collection": ""}
    if not pressed:
        return {r: NOT_READ for r in Rung}, {"state": "not_read", "passages": [], "collection": ""}
    collection = ""
    try:
        store = (store_factory or nd.default_store)()
        collection = nd.collection_for(store, slug)
        if not store.collection_exists(collection):
            # A run row with no collection: the index lost it, so the files are not searchable — not "no hits".
            return {r: UNAVAILABLE for r in Rung}, {"state": "unavailable", "passages": [], "collection": collection}
        hits = store.search(question, [collection], top_k=TOP_K)
    except Exception:
        log.warning("narrative search of %s failed", slug, exc_info=True)
        return {r: UNAVAILABLE for r in Rung}, {"state": "unavailable", "passages": [], "collection": collection}
    passages = [passage_of(h) for h in hits[:TOP_K]]
    if not passages:
        return {r: NO_MATCH for r in Rung}, {"state": "no_match", "passages": [], "collection": collection}
    return _rungs(passages), {"state": "found", "passages": passages, "collection": collection}
