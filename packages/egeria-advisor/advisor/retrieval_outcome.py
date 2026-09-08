"""Why retrieval had nothing to build context from — distinguished, not collapsed.

`RAGRetriever.build_context()` used to return the bare string
"No relevant code found." for four genuinely different situations:

  1. retrieval ran and nothing scored above `min_score`
  2. the collection is empty (ingested, zero rows match)
  3. the collection was never ingested
  4. the vector store was unreachable

A reader — and the LLM downstream — could not tell them apart, so an
infrastructure failure (4) read exactly like "the corpus has nothing on
that" (1). See docs/ea-context-compilation-design.md §6/§7 step 0.

**Vocabulary reuse, not a shared import.** The states below use the same
string values as `resource_explorer.surveyors.result_status` /
`resource_explorer.facts.FactLayer` (measured / nothing_found /
not_established / never_run / partial) — the workspace-wide
absence-is-a-first-class-result vocabulary that design doc's §5 says EA
should borrow rather than reinvent. EA has no python dependency on the
resource-explorer package today (it only reads RE's Postgres tables over
SQL, never imports RE's code), and step 0 is required to add none — so
this is a deliberate value-level match kept as EA's own copy, not a cross-
package import. If EA ever does add a dependency on resource-explorer (or
a shared vocabulary package), these constants should be replaced by that
import rather than kept as a second definition.

Mapping used here:
  - "below_threshold" (case 1) and "collection_empty" (case 2) both mean
    we looked and there is a genuine, measured zero -> NOTHING_FOUND.
    They differ in `reason`/`message`, not in state, because both really
    are real zeros; case 4's rule is about state, not about every pair of
    cases needing a distinct one.
  - "never_ingested" (case 3) -> NEVER_RUN: nothing is known either way,
    because nothing was ever indexed.
  - "store_unreachable" (case 4) -> NOT_ESTABLISHED: an attempt was made
    and this layer cannot be credited with a result. This is the one that
    must never render as NOTHING_FOUND — a fact about us (the store was
    down) is never a fact about the corpus (nothing there).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

# Borrowed vocabulary (see module docstring) — same string values as
# resource_explorer.surveyors.result_status.
MEASURED = "measured"
NOTHING_FOUND = "nothing_found"
NOT_ESTABLISHED = "not_established"
NEVER_RUN = "never_run"


def _fmt_collections(collections: Sequence[str]) -> str:
    if not collections:
        return ""
    return f" (collections searched: {', '.join(collections)})"


@dataclass(frozen=True)
class RetrievalOutcome:
    """Why `build_context()` has nothing to show, and what to say about it.

    `state` is the borrowed FactLayer-style vocabulary; `reason` is a
    short machine-readable code for the specific one of the four (or
    "unknown") situations; `message` is the human-readable sentence that
    replaces the old bare "No relevant code found."
    """

    state: str
    reason: str
    message: str
    min_score: Optional[float] = None
    collections: Tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "message": self.message,
            "min_score": self.min_score,
            "collections": list(self.collections),
        }

    # ------------------------------------------------------------------
    # Factories — one per case.
    # ------------------------------------------------------------------

    @staticmethod
    def below_threshold(min_score: float, collections: Sequence[str] = ()) -> "RetrievalOutcome":
        """Case 1: retrieval ran and nothing scored above `min_score`."""
        return RetrievalOutcome(
            state=NOTHING_FOUND,
            reason="below_threshold",
            message=(
                f"Retrieval ran and found results, but none scored at or above "
                f"the minimum relevance threshold (min_score={min_score:.2f})"
                f"{_fmt_collections(collections)}. This is a real, measured zero — "
                f"the corpus was searched; nothing matched closely enough."
            ),
            min_score=min_score,
            collections=tuple(collections),
        )

    @staticmethod
    def collection_empty(collections: Sequence[str] = ()) -> "RetrievalOutcome":
        """Case 2: the collection has been ingested but holds no matching rows."""
        return RetrievalOutcome(
            state=NOTHING_FOUND,
            reason="collection_empty",
            message=(
                f"The searched collection(s) have been ingested but contain no "
                f"indexed content{_fmt_collections(collections)}. This is a real, "
                f"measured zero — there is genuinely nothing there to find."
            ),
            collections=tuple(collections),
        )

    @staticmethod
    def never_ingested(collections: Sequence[str] = ()) -> "RetrievalOutcome":
        """Case 3: the collection was never ingested at all."""
        return RetrievalOutcome(
            state=NEVER_RUN,
            reason="never_ingested",
            message=(
                f"The searched collection(s) have never been ingested"
                f"{_fmt_collections(collections)}. Nothing is known either way — "
                f"this is not a statement about the corpus, because no content has "
                f"ever been indexed here."
            ),
            collections=tuple(collections),
        )

    @staticmethod
    def store_unreachable(detail: str, collections: Sequence[str] = ()) -> "RetrievalOutcome":
        """Case 4: the vector store could not be reached.

        A fact about us — never a fact about the corpus. Must never render
        as "nothing found".
        """
        return RetrievalOutcome(
            state=NOT_ESTABLISHED,
            reason="store_unreachable",
            message=(
                f"The vector store could not be reached, so retrieval did not "
                f"run{_fmt_collections(collections)}. This is an infrastructure "
                f"failure, not a fact about the corpus — it says nothing about "
                f"whether relevant content exists. Detail: {detail}"
            ),
            collections=tuple(collections),
        )

    @staticmethod
    def unknown() -> "RetrievalOutcome":
        """Degenerate case: `build_context()` was called with no results and
        no retrieval diagnostics attached (e.g. called directly, bypassing
        `retrieve()`). Genuinely unknown which of the four cases applies —
        say so rather than guessing."""
        return RetrievalOutcome(
            state=NOT_ESTABLISHED,
            reason="unknown",
            message=(
                "No relevant code found, and which of the known reasons "
                "(below threshold, empty collection, never ingested, store "
                "unreachable) applies could not be determined here."
            ),
        )
