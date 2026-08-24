"""Batch import/export of resources as CSV — an inventory that is also a scorecard.

Registering resources one at a time does not scale to the corpus sizes that
actually surface bugs: of the nine repos here with a derived homepage, three
exhibited shapes nobody anticipated (a meta-refresh stub, a homepage pointing at
the code forge, a dead domain). Breadth is the limiting factor, so loading it has
to be cheap.

**The one rule that keeps this honest: import reads intent, never state.**

Two kinds of column live in this file and they have opposite lifecycles:

  * *Intent* — what a human decided: which resources to track, what group they
    belong to, what disposition they have been given. Stable, hand-edited,
    meaningful to re-apply.
  * *Observed state* — what RE found: whether something is registered, cataloged
    in Egeria, when it was last surveyed. Derived, changes without anyone
    touching the file, and already has a source of truth in the registry.

Every observed column is prefixed `status_` and is **ignored on import**. Without
that rule the format is ambiguous in a way that cannot be resolved later: is
`status_surveyed_at=2026-08-01` a record of something that happened, or an
instruction to make it so? Worse, an export taken on Tuesday still asserts
`status_cataloged=yes` on Friday after Egeria was reset — a file that looks like
a record while being wrong. Reading state back in would let that fiction write
itself into the registry.

So the export is a superset of the import: it round-trips, it is reviewable in a
spreadsheet, it can be sliced by group to ask "did every ASF repo fail homepage
derivation?" — and re-importing it is exactly as safe as re-importing the list
you started from.

Disposition is deliberately on the *intent* side even though it is also current
state, because it is a human judgement rather than an observation: bulk-tagging a
cohort as `tracking` is a real thing to want, and disposition is keyed by URL so
it can be set before a resource is ever registered.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

RESOURCE_TYPES = ("repo", "database", "filesystem")

# Columns a human fills in. Only `resource_type` and `address` are required.
INTENT_COLUMNS = (
    "resource_type",        # repo | database | filesystem
    "address",              # the natural key — see resource_key()
    "display_name",
    "group",
    "subpath",              # repos only: monorepo sub-project path
    "disposition",
    "disposition_reason",
    "notes",
)

# Columns RE writes and never reads back. The prefix is the contract.
STATUS_COLUMNS = (
    "status_registered",      # is it in RE's registry at all
    "status_slug",            # what RE called it, once registered
    "status_cataloged",       # has an Egeria asset GUID
    "status_egeria_link",     # ok | stale — see egeria_linkage.py
    "status_last_surveyed_at",
    "status_last_published_at",
    "status_lifecycle",       # active | archived | ...
    "status_indexed",         # has RAG collections
)

ALL_COLUMNS = INTENT_COLUMNS + STATUS_COLUMNS

# Import is repo-only for now, and says so rather than skipping quietly.
# Databases need credentials, which have no business in a shared CSV, and
# filesystems need mount points that are meaningful only on one machine —
# both are exported, neither is registerable from this format yet.
IMPORTABLE_TYPES = ("repo",)


def normalize_github_url(url: str) -> str:
    """The same normalization registry.get_by_github_url() applies.

    Duplicated deliberately rather than imported: this must work on a CSV row
    before any registry lookup happens, so that dedup within the file itself
    (the same repo listed twice with and without .git) is caught too.
    """
    return (url or "").strip().lower().rstrip("/").removesuffix(".git")


def github_org_from_url(address: str) -> str:
    """The org/user name if this URL names a whole account rather than one repo.

    A repo URL has two path segments (`github.com/apache/airflow`); an account
    has one (`github.com/apache`). People list both — a foundation's page is the
    obvious thing to copy when the point is "everything these people publish" —
    and treating an account URL as a repo simply fails to fetch, which surfaces
    as an unexplained empty result rather than "that is an organisation".

    Returns "" when the URL is a repo, is not GitHub, or is neither.
    """
    from urllib.parse import urlparse

    u = (address or "").strip()
    if not u:
        return ""
    parsed = urlparse(u if "://" in u else f"https://{u}")
    if "github.com" not in (parsed.netloc or "").lower():
        return ""
    parts = [seg for seg in (parsed.path or "").split("/") if seg]
    # /orgs/<name> is GitHub's own canonical URL for an organisation and is what
    # the browser address bar shows on an org page, so it is at least as likely
    # to be pasted as the short form.
    if len(parts) == 2 and parts[0].lower() == "orgs":
        return parts[1].removesuffix(".git")
    if len(parts) != 1:
        return ""
    name = parts[0].removesuffix(".git")
    # Not every one-segment path is an account: these are GitHub's own pages.
    if name.lower() in {"orgs", "topics", "search", "explore", "features",
                        "marketplace", "sponsors", "settings", "notifications"}:
        return ""
    return name


def resource_key(resource_type: str, address: str) -> str:
    """Stable identity for a resource, independent of RE's slug.

    The slug is RE's own name for something and is derived, so keying an
    interchange format on it would break the moment a repo is registered under a
    different slug (a monorepo sub-project, say). The address is what the user
    actually knows.
    """
    if resource_type == "repo":
        return normalize_github_url(address)
    # Databases (host:port/name) and filesystems (mount point) are already
    # natural keys; only case and trailing separators need settling.
    return (address or "").strip().rstrip("/").lower()


@dataclass
class ImportRow:
    resource_type: str
    address: str
    display_name: str = ""
    group: str = ""
    subpath: str = ""
    disposition: str = ""
    disposition_reason: str = ""
    notes: str = ""
    line: int = 0                      # 1-based CSV line, for error messages
    errors: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return resource_key(self.resource_type, self.address)


def describe_skipped(row: "ImportRow", max_value: int = 80) -> str:
    """One line naming where a skipped row was and what was on it.

    The line number alone is enough to find it in an editor; the value is what
    makes the problem obvious without going and looking. In a 500-row file the
    difference between "line 312: not a URL" and
    `line 312: "htps://github.com/a/b" — not a URL` is the difference between a
    hunt and a fix.

    Truncated because a malformed CSV row can be enormous — a whole record
    collapsed into one cell — and one bad row must not flood the report.
    """
    value = (row.address or "").strip()
    if not value:
        shown = "(empty)"
    elif len(value) > max_value:
        shown = f'"{value[:max_value]}…"'
    else:
        shown = f'"{value}"'
    return f"line {row.line}: {shown} — {'; '.join(row.errors)}"


@dataclass
class ImportPlan:
    """What a file would do, computed before anything is written."""
    to_register: list[ImportRow] = field(default_factory=list)
    already_registered: list[ImportRow] = field(default_factory=list)
    unsupported_type: list[ImportRow] = field(default_factory=list)
    invalid: list[ImportRow] = field(default_factory=list)
    duplicate_in_file: list[ImportRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (len(self.to_register) + len(self.already_registered)
                + len(self.unsupported_type) + len(self.invalid)
                + len(self.duplicate_in_file))


_VALID_DISPOSITIONS = {"undecided", "tracking", "investigating", "ignored", "abandoned", "using"}


def parse_csv_text(text: str) -> list[ImportRow]:
    """Parse a pasted/uploaded list — CSV, or one address per line.

    Accepting both is not indulgence: the two natural ways to arrive here are a
    spreadsheet export and a list someone pasted out of a wiki, and rejecting the
    second would push people back to registering one at a time. A file with no
    delimiter and no recognised header is treated as one address per line; blank
    lines and `#` comments are skipped so an annotated list still works.
    """
    import io

    lines = [ln for ln in (text or "").splitlines()]
    meaningful = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not meaningful:
        return []

    header = meaningful[0].lower()
    looks_like_csv = "," in header and ("address" in header or "resource_type" in header)
    if looks_like_csv:
        return _parse_rows(csv.DictReader(io.StringIO("\n".join(meaningful))))

    # Plain list. Keep the original line numbers so error messages point at the
    # file the user is looking at, not at the filtered subset.
    rows: list[ImportRow] = []
    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        row = ImportRow(resource_type="repo", address=line, line=idx)
        if " " in line:
            row.errors.append("not a URL (contains a space) — if this is a CSV, "
                              "it needs an 'address' column header")
        elif "," in line:
            # Reached plain-list mode with comma-separated content, which means
            # the header sniff failed — an exported file whose header row was
            # edited or dropped is the likely cause. Without this the whole row
            # is treated as one URL and sent to GitHub, coming back as
            # "unreachable", which points at the network instead of the header.
            row.errors.append("looks like a CSV row, but the file has no "
                              "recognised header — the first line must include "
                              "an 'address' column")
        rows.append(row)
    return rows


def parse_csv(path: str | Path) -> list[ImportRow]:
    """Read intent rows. Unknown columns are ignored, not rejected.

    Ignoring rather than rejecting is what lets an exported scorecard — which
    carries every status_ column — be handed straight back to import without
    editing. That round-trip is the whole point of the prefix convention.
    """
    rows: list[ImportRow] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return rows
        known = {c.strip().lower() for c in reader.fieldnames if c}
        if "address" not in known:
            raise ValueError(
                "CSV has no 'address' column. Required columns are resource_type and "
                f"address; optional: {', '.join(c for c in INTENT_COLUMNS[2:])}.")
        return _parse_rows(reader)


def _parse_rows(reader) -> list[ImportRow]:
    """Shared row loop for the file and text entry points, so validation cannot
    differ between the CLI and the UI."""
    rows: list[ImportRow] = []
    if True:
        for i, raw in enumerate(reader, start=2):   # start=2: line 1 is the header
            get = lambda k: (raw.get(k) or "").strip()  # noqa: E731
            row = ImportRow(
                resource_type=get("resource_type").lower() or "repo",
                address=get("address"),
                display_name=get("display_name"),
                group=get("group"),
                subpath=get("subpath"),
                disposition=get("disposition").lower(),
                disposition_reason=get("disposition_reason"),
                notes=get("notes"),
                line=i,
            )
            if not row.address:
                row.errors.append("no address")
            if row.resource_type not in RESOURCE_TYPES:
                row.errors.append(
                    f"unknown resource_type '{row.resource_type}' "
                    f"(expected one of {', '.join(RESOURCE_TYPES)})")
            if row.disposition and row.disposition not in _VALID_DISPOSITIONS:
                row.errors.append(f"unknown disposition '{row.disposition}'")
            if row.resource_type == "repo" and row.address and "github.com" not in row.address.lower():
                # Not fatal — GitHub Enterprise hosts are legitimate — but worth
                # saying, since a typo'd URL otherwise fails much later with a 404
                # during import, one repo at a time.
                log.debug("row %d: %s is not a github.com URL", i, row.address)
            rows.append(row)
    return rows


def plan_import(registry, rows: list[ImportRow]) -> ImportPlan:
    """Classify every row without writing anything.

    Separate from execution so `--dry-run` and the real run agree by
    construction: a plan you cannot inspect before a few hundred writes is not
    much of a safeguard.
    """
    plan = ImportPlan()
    existing = _existing_keys(registry)
    seen: set[str] = set()

    for row in rows:
        if row.errors:
            plan.invalid.append(row)
        elif row.key in seen:
            row.errors.append("duplicate of an earlier row in this file")
            plan.duplicate_in_file.append(row)
        elif row.key in existing:
            plan.already_registered.append(row)
        elif row.resource_type not in IMPORTABLE_TYPES:
            row.errors.append(
                f"{row.resource_type} rows are exported but cannot be registered from CSV "
                "(databases need credentials, filesystems need machine-local mount points)")
            plan.unsupported_type.append(row)
        else:
            plan.to_register.append(row)
        if not row.errors:
            seen.add(row.key)
    return plan


def _existing_keys(registry) -> set[str]:
    """Every resource RE already has, by natural key.

    Built once per import rather than a lookup per row: get_by_github_url scans
    the whole projects table and normalizes in Python, so a few hundred rows
    would otherwise be a few hundred full scans.
    """
    keys: set[str] = set()
    for p in registry.list_all():
        keys.add(resource_key("repo", p.github_url))
    for d in getattr(registry, "list_databases", lambda: [])():
        keys.add(resource_key("database", f"{d.host}:{d.port}/{d.database_name}"))
    for f in getattr(registry, "list_filesystems", lambda: [])():
        keys.add(resource_key(
            "filesystem", f.canonical_mount_point or f.local_mount_point))
    return keys


def export_rows(registry) -> list[dict[str, Any]]:
    """Current state of every registered resource, as scorecard rows.

    Every value here is read from the registry at call time. Nothing is cached,
    because a stale scorecard that looks authoritative is the failure mode this
    format is most likely to produce.
    """
    out: list[dict[str, Any]] = []

    def _linkage(entity_type: str, slug: str) -> str:
        try:
            row = registry.get_egeria_linkage(entity_type, slug)
        except Exception as exc:
            # "unknown", not "" — an empty cell in a scorecard reads as "fine",
            # and a column that cannot distinguish "healthy" from "could not
            # tell" is worse than no column.
            log.warning("linkage lookup failed for %s/%s: %s", entity_type, slug, exc)
            return "unknown"
        return "stale" if row and row.get("status") == "stale" else "ok"

    for p in registry.list_all():
        # Deliberately unguarded. These read the same registry that produced the
        # list being iterated, so a failure here is not a per-row problem — it is
        # the registry being unavailable, and an export that carries on would
        # emit hundreds of rows with silently empty disposition and publish
        # columns. A scorecard assembled from a registry we could not read is
        # worse than an error, because it looks like an answer.
        disp = registry.get_disposition(p.github_url) or {}
        latest = registry.get_latest_egeria_survey(p.slug)
        published = (latest or {}).get("published_at", "") if latest else ""
        out.append({
            "resource_type": "repo",
            "address": p.github_url,
            "display_name": p.display_name,
            "group": p.group_slug or "",
            "subpath": p.subproject_path or "",
            "disposition": disp.get("disposition", ""),
            "disposition_reason": disp.get("reason", ""),
            "notes": "",
            "status_registered": "yes",
            "status_slug": p.slug,
            "status_cataloged": "yes" if p.egeria_asset_guid else "no",
            "status_egeria_link": _linkage("repo", p.slug),
            "status_last_surveyed_at": p.last_surveyed_at or "",
            "status_last_published_at": published or "",
            "status_lifecycle": p.status or "",
            "status_indexed": "yes" if (p.collections or []) else "no",
        })

    for d in getattr(registry, "list_databases", lambda: [])():
        out.append({
            "resource_type": "database",
            "address": f"{d.host}:{d.port}/{d.database_name}",
            "display_name": d.display_name,
            "group": d.group_slug or "",
            "subpath": "", "disposition": "", "disposition_reason": "", "notes": "",
            "status_registered": "yes",
            "status_slug": d.slug,
            "status_cataloged": "yes" if d.egeria_asset_guid else "no",
            "status_egeria_link": _linkage("database", d.slug),
            "status_last_surveyed_at": d.last_surveyed_at or "",
            "status_last_published_at": "",
            "status_lifecycle": d.status or "",
            "status_indexed": "",
        })

    for f in getattr(registry, "list_filesystems", lambda: [])():
        out.append({
            "resource_type": "filesystem",
            "address": f.canonical_mount_point or f.local_mount_point,
            "display_name": f.display_name,
            "group": f.group_slug or "",
            "subpath": "", "disposition": "", "disposition_reason": "", "notes": "",
            "status_registered": "yes",
            "status_slug": f.slug,
            "status_cataloged": "yes" if f.egeria_asset_guid else "no",
            "status_egeria_link": _linkage("filesystem", f.slug),
            "status_last_surveyed_at": f.last_surveyed_at or "",
            "status_last_published_at": "",
            "status_lifecycle": f.status or "",
            "status_indexed": "",
        })
    return out


def write_csv(rows: list[dict[str, Any]], path: str | Path) -> int:
    """Write scorecard rows, always with the full column set.

    Every column every time, even when empty: a file whose columns vary with its
    contents cannot be diffed against last week's, which is most of what a
    running scorecard is for.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ALL_COLUMNS))
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in ALL_COLUMNS})
    return len(rows)
