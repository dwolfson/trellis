"""The architecture document as a LENS over recovered components (finding 101).

Dan, 2026-08-24: *"you need to look at code through the lens of the
documentation — and good documentation will guide you towards what code to look
at for which purpose. Just looking at the code doesn't provide enough context to
easily distinguish between internal and external communications."*

Milvus is the proof. Recovery reports 296 rpcs across 18 gRPC services; the
number a reader wants for runtime suitability is `proxy.proto`'s 18, because
`proxy` is the client-facing service and the coord services are internal.
Nothing in the code says so. Milvus's own documentation says it plainly — and
that same document is where this project's ground-truth fixture came from,
transcribed **by hand**. The system has never done automatically what we did
manually to build every fixture it is scored against.

**A lens, not an oracle.** This module ranks and labels what the detectors
already proposed. It never adds a component, never removes one, and never
overrides a type. Two reasons, both learned the hard way:

* The document can be stale. `OpenLineage/OpenLineage`'s architecture doc is
  dated 2023-11-03 — measured, not hypothesised — and findings 65-68 are
  entirely about correlating doc version against code version rather than
  trusting the prose.
* A document that disagrees with the code is a **finding**, not a correction.
  "The doc names a component we did not find" is one of the more useful things
  this system can say, and silently adopting it would destroy exactly that.

**Scope, measured 2026-08-24 across the 46 gate-approved repos:** 13 have an
architecture document located, 4 in-repo and **9 in a sibling repository**. The
sibling majority is the real argument — a code-only reader cannot reach those by
any amount of better parsing, which makes this a wrong-corpus problem rather
than a precision one. The remaining 31 were never looked at, because `EXPECTED`
asks for `architecture` only for `application` and `middleware`; they are an
unmeasured population, not a measured absence.

**Extraction is deliberately dumb.** Headings, bold spans and code spans, in a
markdown document, under a length cap. No NLP, no model. A term is a candidate
name only because the author gave it structural emphasis, which is explainable
and regression-testable where a prompt is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import doc_locations as dl

#: Structural emphasis a document author uses for a component name.
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.M)
_BOLD_RE = re.compile(r"\*\*([^*\n]{2,60})\*\*")
_CODE_RE = re.compile(r"`([^`\n]{2,60})`")

#: Words that are structurally emphasised in every architecture document and
#: name nothing. Kept short on purpose: an over-eager stop list would silently
#: drop real component names, and a false candidate merely fails to match.
_STOPWORDS = frozenset({
    "overview", "architecture", "introduction", "contents", "summary",
    "components", "component", "design", "notes", "note", "see also",
    "references", "reference", "background", "goals", "non-goals",
    "table of contents", "getting started", "prerequisites", "appendix",
})

#: Compared in normalised form — see `extract_terms`.
_NORMALISED_STOPWORDS = frozenset()   # populated below, after _normalise exists

#: Cap on document size read. A generated or book-length doc is not worth
#: unbounded memory for a Discovery-tier labelling pass.
MAX_DOC_CHARS = 400_000

#: Cap on chunks pulled back from an ingested collection. A site can be
#: thousands of chunks (egeria-project.org is 6018); the lens only needs enough
#: emphasised text to recognise component names, and the terms it extracts are
#: a set, so more chunks stop adding new ones quickly.
MAX_INGESTED_CHUNKS = 800

#: Cap on FILES read, which is the real cost: each one is an API call.
#: `milvus-io/milvus`'s `docs/design-docs` holds 80 markdown files one level
#: down, and reading all of them would put this well outside the tier it claims.
#: Whatever is dropped is reported — a bounded read that says so is honest; a
#: bounded read that stays quiet reads as "the document said nothing more".
MAX_DOC_FILES = 25

#: Filenames that are most likely to describe the system as a whole, read first
#: when the cap bites. Everything else keeps its natural order behind them.
_OVERVIEW_HINTS = ("readme", "architecture", "overview", "design", "components",
                   "system", "introduction")

_DOC_EXTS = (".md", ".mdx", ".rst", ".txt")

#: Where a documentation-site repository keeps its prose. `contents` is not a
#: typo for `content` — Gatsby uses the plural and `MarquezProject/website` is
#: the live case; both are listed because guessing which convention a site
#: follows is not something a keyword search should have to do.
_SITE_CONTENT_DIRS = ("docs", "content", "contents", "website/pages", "pages",
                      "src/pages", "guides", "documentation")


@dataclass
class DocLens:
    """What the document says, and how it lines up with what was proposed."""
    outcome: str = "not-found"          # dl.Outcome — where the READ document was found
    evidence: str = ""                  # path / owner:path / URL of the read document
    #: Every location found, read or not. Documentation is plural: OpenLineage
    #: has six architecture sources and Milvus twelve, and a single-answer model
    #: discarded all but one. Unreadable ones (a `doc-site`) belong here too —
    #: they are sources we know about and cannot use, which is exactly what a
    #: recommendation to ingest them attaches to.
    sources: list = field(default_factory=list)   # list[(outcome, evidence)]
    read_sources: list = field(default_factory=list)  # the ones actually consulted
    date: str | None = None             # last-commit date of the document
    terms: list = field(default_factory=list)        # candidate names it emphasises
    documented: dict = field(default_factory=dict)   # component slug -> matched term
    #: `{slug: EVIDENCE_*}` — how each entry in `documented` was established.
    #: Emphasis in a source document is a stronger claim than a mention in an
    #: ingested site, and collapsing them would over-state the weaker one.
    evidence_kind: dict = field(default_factory=dict)
    undetected: list = field(default_factory=list)   # doc names we did NOT propose
    #: Whether `undetected` means anything. See `undetected_is_meaningful`.
    undetected_usable: bool = False
    undetected_reason: str = ""
    notes: list = field(default_factory=list)

    @property
    def consulted(self) -> bool:
        """Whether a document was actually read.

        Keys on `read_sources`, not on `terms`. Keying on terms was wrong the
        moment ingested sites became readable: an ingested site is rendered HTML
        converted to text, so `extract_terms` — which needs markdown emphasis —
        finds nothing in it, and `unitycatalog` read 26 chunks and still
        reported "document not consulted". Extracting nothing from a document is
        not the same as never opening one, which is the distinction this
        property exists to make.
        """
        return bool(self.read_sources) or bool(self.terms)


def _normalise(term: str) -> str:
    """Lowercase, strip markdown/punctuation noise, collapse separators.

    `proxy`, `Proxy`, `**Proxy**`, `proxy/` and `Proxy Node` must all be
    comparable to a component slugged `proxy`.
    """
    t = re.sub(r"[`*_\[\]()<>/\\]+", " ", term).strip().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


_NORMALISED_STOPWORDS = frozenset(
    _normalise(w) for w in _STOPWORDS) | frozenset(_STOPWORDS)


def extract_terms(text: str) -> list[str]:
    """Candidate component names from a markdown document, in first-seen order.

    Structural emphasis only. A term that is really prose ("Getting Started")
    simply fails to match a component later, which costs nothing — whereas a
    cleverer extractor that dropped a real name would cost recall silently.
    """
    seen: dict[str, str] = {}
    for pattern in (_HEADING_RE, _BOLD_RE, _CODE_RE):
        for raw in pattern.findall(text[:MAX_DOC_CHARS]):
            norm = _normalise(raw)
            # Compare against NORMALISED stopwords. Comparing a normalised term
            # against raw ones let "table of contents" through as
            # "table-of-contents" — the stop list looked right and did nothing
            # for every multi-word entry in it.
            if not norm or norm in _NORMALISED_STOPWORDS:
                continue
            if len(norm) < 3 or norm.isdigit():
                continue
            seen.setdefault(norm, raw.strip())
    return list(seen)


#: How a component came to be called documented. Not cosmetic: emphasis in a
#: markdown document is a much stronger claim than a mention in rendered HTML,
#: and a reader who cannot tell them apart will over-trust the weaker one.
EVIDENCE_EMPHASISED = "emphasised"   # a heading, bold or code span in the source doc
EVIDENCE_MENTIONED = "mentioned"     # the name appears in an ingested site's text

#: Words that would match half a corpus. A component legitimately named `index`
#: is not evidenced by a documentation site containing the word "index".
_TOO_GENERIC = frozenset({
    "index", "core", "common", "utils", "util", "main", "src", "lib", "api",
    "app", "test", "tests", "docs", "doc", "build", "config", "server",
    "client", "service", "data", "base", "model", "models", "types", "internal",
})


def find_mentions(text: str, components: list) -> dict:
    """`{slug: name}` for components whose name appears in `text`.

    A deliberately weaker test than `extract_terms`, for a deliberately weaker
    source. Ingested site content is rendered HTML converted to text, so the
    markdown emphasis `extract_terms` depends on is gone — running it over
    `sqlglot`'s ingested site yielded twelve terms, all code fragments.

    So for ingested text the question changes from *"what does this document
    emphasise"* to *"does this document mention this component"*, which needs no
    markup. Word-boundary matched, minimum four characters, and generic names
    excluded — a component called `index` is not evidenced by a site containing
    the word "index".

    Reported as `EVIDENCE_MENTIONED` so it is never confused with emphasis.
    """
    low = text.lower()
    found: dict = {}
    for c in components:
        for key in sorted(_component_keys(c), key=len, reverse=True):
            if len(key) < 4 or key in _TOO_GENERIC:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", low):
                found.setdefault(getattr(c, "slug", key), key)
                break
    return found


def undetected_is_meaningful(terms: list, components: list) -> tuple:
    """`(usable, reason)` — is `undetected` a list of things we failed to detect,
    or just a document's own section structure?

    Measured 2026-08-25, and the shapes are not close:

    ```
    amundsen      4 terms / 43 components    100% matched   an overview
    sqlglot      12 terms / 11 components     50%           an overview
    milvus     1140 terms / 206 components     2%           25 design documents
    openlineage 713 terms / 124 components     3%           a documentation site
    ```

    The rule is a **comparison, not a threshold**: a document that emphasises
    more things than the repository has components is describing its own
    structure — headings, steps, options — and its unmatched emphasis says
    nothing about components we missed. An architecture overview emphasises
    fewer things than there are components, because it names the important ones.

    Deliberately not tuned. `terms <= components` needs no constant, cannot be
    quietly adjusted to make a number look better, and states the claim it rests
    on: **emphasis at scale is structure, not naming.**
    """
    n_terms, n_comps = len(terms), len(components)
    if not n_terms:
        return False, "no emphasised terms were extracted"
    if not n_comps:
        return False, "no components to compare against"
    if n_terms > n_comps:
        return False, (
            f"the document set emphasises {n_terms} terms against {n_comps} "
            f"recovered component(s) — at that ratio emphasis is section "
            f"structure rather than component naming, so unmatched terms are "
            f"headings, not components we missed")
    return True, (
        f"{n_terms} emphasised term(s) against {n_comps} component(s) — few "
        f"enough that emphasis plausibly names components, so unmatched terms "
        f"are worth reading")


def _component_keys(component) -> set:
    """The names a component could legitimately be called in prose."""
    keys = set()
    for value in (getattr(component, "slug", ""), getattr(component, "name", "")):
        n = _normalise(str(value or ""))
        if n:
            keys.add(n)
            keys.add(n.split("-")[-1])      # `milvus-proxy` also answers to `proxy`
    return {k for k in keys if len(k) >= 3}


def apply(owner_repo: str, components: list, client=None,
          locations=None) -> DocLens:
    """Resolve the architecture document and label `components` against it.

    Never mutates `components`. Returns what matched, what the document names
    that nothing proposed, and where the document came from — all three matter,
    and the third most: a `sibling-repo` answer is the case that justifies this
    whole path.
    """
    lens = DocLens()
    try:
        arts = dl.find_artifacts(owner_repo, "architecture", client=client,
                                 locations=locations)
    except Exception as exc:  # noqa: BLE001 - degraded, never fatal
        lens.notes.append(f"architecture document lookup failed: {exc}")
        return lens

    lens.sources = [(a.outcome, a.evidence) for a in arts if a.evidence]
    readable = [a for a in arts if a.outcome in ("in-repo", "sibling-repo")]
    unreadable = [a for a in arts if a.outcome == "doc-site"]

    if not lens.sources:
        lens.notes.append("no architecture document located — nothing to read")
        return lens
    if not readable:
        # Before giving up: the site may already be INGESTED. That is the whole
        # point of ingesting it, and until now the lens could not use it —
        # `sqlglot`'s site was 97 chunks in pgvector while this reported
        # "located, not readable".
        ingested_text, collection = _ingested_text_for(owner_repo, unreadable,
                                                       lens.notes)
        if ingested_text:
            lens.outcome, lens.evidence = "ingested-site", collection
            lens.terms = extract_terms(ingested_text)
            mentions = find_mentions(ingested_text, components)
            lens.documented.update(mentions)
            for slug in mentions:
                lens.evidence_kind[slug] = EVIDENCE_MENTIONED
            lens.read_sources.append(("ingested-site", collection))
            # Say WHY, rather than leaving the default False to be read as "we
            # looked and it was not meaningful". Ingested text is rendered HTML
            # with no markdown emphasis, so `extract_terms` has nothing to work
            # from and `undetected` is not computed on this path at all — which
            # is a different fact from having computed it and found it useless.
            lens.undetected_usable = False
            lens.undetected_reason = (
                "not computed: this came from an ingested site, whose text has no "
                "markdown emphasis to extract, so components were matched by "
                "mention rather than by emphasis")
            return lens
        lens.notes.append(
            f"{len(unreadable)} documentation site(s) located and none readable from "
            f"here ({', '.join(a.evidence for a in unreadable[:3])}) — located, not "
            f"consulted. Ingesting the site would make these answerable.")
        lens.outcome, lens.evidence = unreadable[0].outcome, unreadable[0].evidence
        lens.date = unreadable[0].date
        return lens

    # Read EVERY readable source, not the first. The first is only "most
    # specific by resolution order", which says nothing about which one
    # actually describes the architecture — measured, OpenLineage's first
    # sibling of five yielded nothing while the corpus average across all
    # sources is what matters.
    texts: list = []
    for art in readable:
        chunk = _read_document(owner_repo, art, client, lens.notes)
        if chunk:
            texts.append(chunk)
            lens.read_sources.append((art.outcome, art.evidence))
            if not lens.evidence:            # attribute to the first that read
                lens.outcome, lens.evidence, lens.date = (
                    art.outcome, art.evidence, art.date)
        if sum(len(t) for t in texts) >= MAX_DOC_CHARS:
            lens.notes.append(
                f"stopped after {len(texts)} source(s) at {MAX_DOC_CHARS} characters")
            break

    if not texts:
        lens.notes.append(
            f"{len(readable)} readable source(s) located, none could be fetched — "
            f"located, not consulted")
        lens.outcome, lens.evidence = readable[0].outcome, readable[0].evidence
        return lens

    text = "\n\n".join(texts)
    lens.terms = extract_terms(text)
    by_key: dict = {}
    for c in components:
        for key in _component_keys(c):
            by_key.setdefault(key, c)

    for term in lens.terms:
        hit = by_key.get(term)
        if hit is not None:
            lens.documented.setdefault(getattr(hit, "slug", term), term)

    for slug in lens.documented:
        lens.evidence_kind.setdefault(slug, EVIDENCE_EMPHASISED)
    matched_terms = set(lens.documented.values())
    lens.undetected = [t for t in lens.terms if t not in matched_terms
                       and t not in lens.documented]
    lens.undetected_usable, lens.undetected_reason = undetected_is_meaningful(
        lens.terms, components)
    return lens


def _ingested_text_for(owner_repo: str, unreadable: list, notes: list):
    """`(text, collection)` if any located site is already in the vector store.

    Collections are keyed on the site's HOST, not the repo — several repos in
    one project share one site and therefore one collection, which is why this
    can find a collection ingested on another repo's behalf.
    """
    from urllib.parse import urlparse
    for art in unreadable:
        host = (urlparse(art.evidence).hostname or "").lower().removeprefix("www.")
        if not host:
            continue
        collection = "web_docs_" + re.sub(r"[^a-z0-9]+", "_", host).strip("_")
        text = read_ingested_site(collection, notes)
        if text:
            return text, collection
    return "", ""


def read_ingested_site(collection: str, notes: list) -> str:
    """Text of a documentation site already ingested into pgvector.

    **This is the point of ingesting it.** `repo_website_ingestion` loads a
    documentation site so Chat and Understanding can answer from it, and until
    now architecture recovery could not touch that — `sqlglot`'s site was 97
    chunks in `web_docs_sqlglot_com` while the lens still reported "located, not
    readable". Ingesting made the document available to everything except the
    step that most needed it.

    The extracted terms then go through exactly the same `extract_terms` as a
    markdown file. That is deliberate: the extraction is the part with measured
    behaviour and a regression suite behind it, and a second path with different
    rules would need its own evidence to be trusted.
    """
    try:
        from resource_explorer.vector_store_pg import PgVectorStore
        store = PgVectorStore()
        store.connect()
        if not store.collection_exists(collection):
            return ""
        rows = store.query_by_filter(collection, output_fields=("text",),
                                     limit=MAX_INGESTED_CHUNKS)
    except Exception as exc:  # noqa: BLE001 - degraded, never fatal
        notes.append(f"could not read ingested collection '{collection}': {exc}")
        return ""
    texts = [str(r.get("text") or "") for r in rows]
    if not texts:
        notes.append(f"ingested collection '{collection}' exists but returned no text")
        return ""
    notes.append(f"read {len(texts)} chunk(s) from ingested site '{collection}'")
    return "\n\n".join(texts)[:MAX_DOC_CHARS]


def _read_document(owner_repo: str, art, client, notes: list) -> str:
    """Fetch the located document's text.

    Handles the three readable shapes — a file in this repo, a directory in this
    repo, and a sibling repository — and descends **one** level into
    subdirectories, matching `doc_locations._find_in_dir`'s deliberate
    shallowness. `milvus-io/milvus` is why the descent exists at all: the
    located artifact is `docs/design-docs`, whose only markdown at the top level
    is an index, with 80 real documents in `design_docs/` beneath it.
    """
    gh = client or dl._make_client()
    if art.outcome == "sibling-repo":
        target, _, path = art.evidence.partition(":")
    else:
        target, path = owner_repo, art.evidence
    try:
        repo = gh.get_repo(target)
        entry = repo.get_contents(path) if path else repo.get_contents("")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"could not fetch {target}:{path or '/'} — {exc}")
        return ""

    # A bare sibling POINTER (no `:path`) resolves to the repo root, whose only
    # markdown is usually a build README. Measured 2026-08-25: nine of thirteen
    # located documents are sibling pointers, and reading their roots yielded
    # 2 terms for `openlineage`, 5 for `marquez`, 0 for `trellis`.
    #
    # The content is there — `OpenLineage/docs` has `docs/guides`,
    # `MarquezProject/website` has `contents/`, `docling-project/website` has
    # `website/pages`. What none of them has is a FILE NAMED "architecture",
    # which is what `doc_locations` searches for and why it returns a pointer
    # rather than a page. **Filename keyword matching is the wrong instrument
    # for a documentation website**: the architecture is described across its
    # guides and concept pages, not filed under that word.
    #
    # So when we hold only a pointer, read the site's documentation directories
    # broadly instead of its root. Same shallow discipline, same file cap.
    if isinstance(entry, list) and not path:
        broadened = []
        for name in _SITE_CONTENT_DIRS:
            try:
                broadened.extend(repo.get_contents(name))
            except Exception:  # noqa: BLE001
                continue
        if broadened:
            notes.append(f"{target} resolved to the repository rather than a page; "
                         f"read its documentation directories instead")
            entry = broadened

    entries = entry if isinstance(entry, list) else [entry]
    files, subdirs = [], []
    for item in entries:
        if getattr(item, "type", "") == "dir":
            subdirs.append(item)
        elif str(item.path).lower().endswith(_DOC_EXTS):
            files.append(item)

    for sub in subdirs:
        try:
            for item in repo.get_contents(sub.path):
                if (getattr(item, "type", "") != "dir"
                        and str(item.path).lower().endswith(_DOC_EXTS)):
                    files.append(item)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"could not search '{sub.path}' — {exc}")

    def _priority(item) -> tuple:
        low = str(item.path).lower()
        for i, hint in enumerate(_OVERVIEW_HINTS):
            if hint in low:
                return (0, i, low)
        return (1, 0, low)

    files.sort(key=_priority)
    total = len(files)
    if total > MAX_DOC_FILES:
        notes.append(
            f"{total} document(s) located, read {MAX_DOC_FILES} — "
            f"overview-shaped filenames first ({', '.join(_OVERVIEW_HINTS[:3])}, "
            f"...). The remainder were NOT read, so an absent term here is not "
            f"evidence the documentation is silent about it.")
        files = files[:MAX_DOC_FILES]

    chunks: list = []
    for item in files:
        try:
            chunks.append(item.decoded_content.decode("utf-8", errors="ignore"))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"could not decode {item.path} — {exc}")
        if sum(len(c) for c in chunks) >= MAX_DOC_CHARS:
            notes.append(
                f"stopped at {MAX_DOC_CHARS} characters — later documents unread")
            break
    if chunks:
        notes.append(f"read {len(chunks)} of {total} located document(s)")
    return "\n\n".join(chunks)
