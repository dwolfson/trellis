"""
DocumentManager — lifecycle management for Governance Plan Documents (GPDs).

Folder layout (all paths configurable in advisor.yaml → governance_plans):
  inbox/     — plans awaiting review or execution
  outbox/    — executed plans with outcome sections appended
  trash/     — soft-deleted plans (single live copy per doc_id, recoverable)
  versions/  — immutable timestamped snapshots, one per mutating operation

Each document is a markdown file named:
  {YYYYMMDD_HHMMSS}_{slug}.md

where slug is a URL-safe version of the plan title. doc_id (the filename
stem) is stable for the document's entire life — it never changes across
inbox/outbox/trash moves.

A document lives in exactly one of inbox/outbox/trash at any time. Deleting
moves a document to trash (not a hard delete) — it can be restored or
permanently purged. versions/ is separate: it accumulates a full edit
history regardless of which folder the document currently lives in.
"""
from __future__ import annotations

import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_paths() -> Dict[str, Path]:
    """Read governance_plans paths from advisor.yaml, expanding ~."""
    base = Path.home() / "egeria-plans"
    defaults = {
        "inbox":    base / "inbox",
        "outbox":   base / "outbox",
        "trash":    base / "trash",
        "versions": base / "versions",
    }
    try:
        cfg_file = Path(__file__).parent.parent / "config" / "advisor.yaml"
        with open(cfg_file) as f:
            cfg = yaml.safe_load(f)
        gp = cfg.get("governance_plans", {})
        base_cfg = Path(gp.get("inbox", str(base / "inbox"))).expanduser().parent
        return {
            "inbox":    Path(gp["inbox"]).expanduser()    if "inbox"    in gp else defaults["inbox"],
            "outbox":   Path(gp["outbox"]).expanduser()   if "outbox"   in gp else defaults["outbox"],
            "trash":    Path(gp["trash"]).expanduser()    if "trash"    in gp else
                        (Path(gp["archived"]).expanduser() if "archived" in gp else defaults["trash"]),
            "versions": Path(gp["versions"]).expanduser() if "versions" in gp else base_cfg / "versions",
        }
    except Exception as exc:
        logger.debug(f"DocumentManager: using default paths — {exc}")
        return defaults


def _slug(title: str) -> str:
    """Convert a plan title to a filesystem-safe slug."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:60].strip("_")


def _doc_id(path: Path) -> str:
    """Return the doc_id (stem) for a given path."""
    return path.stem


_KNOWN_OBJECTS_HEADER_RE = re.compile(
    r'^\|\s*Command\s*\|\s*Status\s*\|\s*GUID\s*\|\s*Qualified Name\s*\|.*\|\s*$',
    re.MULTILINE,
)


def _parse_known_objects(content: str) -> List[Dict[str, str]]:
    """
    Extract {command, qualified_name, guid} rows from a plan's "Command Results"
    table — the GUID/Qualified Name variant produced when commands_detail was
    available from the MCP response (see OutcomeReporter._compose_outcome_section).

    Returns [] if no such table is present (e.g. plan was never executed, or the
    MCP didn't return per-command detail).
    """
    header_match = _KNOWN_OBJECTS_HEADER_RE.search(content)
    if not header_match:
        return []

    objects: List[Dict[str, str]] = []
    for line in content[header_match.end():].splitlines():
        line = line.strip()
        if not line:
            continue  # blank line right after the header doesn't end the table
        if not line.startswith("|"):
            break  # table ended
        if re.match(r'^\|[\s:-]+\|', line):
            continue  # separator row
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 4:
            continue
        command, _status, guid, qualified_name = cols[0], cols[1], cols[2], cols[3]
        if guid and qualified_name:
            objects.append({"command": command, "qualified_name": qualified_name, "guid": guid})
    return objects


def _replace_title(content: str, new_title: str) -> str:
    """Replace the first H1 line in a plan document with new_title."""
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("# "):
            lines[i] = f"# {new_title}"
            return "\n".join(lines)
    return f"# {new_title}\n\n" + content


def _set_header_field(content: str, label: str, value: str) -> tuple[str, bool]:
    """
    Replace `**{label}:** <value>` in the document header with a new value.
    A field's value ends at the next bold marker (2+ spaces then `**`, the
    separator _compose_document uses between header fields) or end of line.
    Returns (new_content, found) — found=False means the label isn't present.
    """
    pattern = re.compile(rf'(\*\*{re.escape(label)}:\*\*\s*)([^\n]*?)(?=  +\*\*|\n)')
    new_content, n = pattern.subn(lambda m: m.group(1) + value, content, count=1)
    return new_content, n > 0


def touch_edit_header(content: str, editor: str) -> str:
    """
    Update a plan document's '**Last edited:**' / '**Last edited by:**' header
    fields to the current time and the given user, on every save.

    This is a lightweight "who touched this doc last" hint for the plan
    authoring UI, not a substitute for real audit history — Egeria itself
    tracks full version history server-side once elements are actually
    created/updated there.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    content, _ = _set_header_field(content, "Last edited", now)
    content, found = _set_header_field(content, "Last edited by", editor)
    if not found:
        # Documents composed before "Last edited by" existed — add it right
        # after "Created by: <value>" on the same header line.
        content, _ = re.subn(
            r'(\*\*Created by:\*\*\s*[^\n]*?)(  +\*\*|\n)',
            rf'\g<1>   **Last edited by:** {editor}\g<2>',
            content, count=1,
        )
    return content


_VERSION_NOTE_RE = re.compile(r'^<!--\s*version_note:\s*(.*?)\s*-->\n')


def describe_changes(old_content: str, new_content: str) -> str:
    """
    Best-effort, non-specific summary of what changed between two versions of
    a plan document — good enough to show next to a version snapshot, not a
    real diff. Compares H2 ("## ...") blocks positionally and names which ones
    differ, drilling into the single differing H3 ("### ...") field when
    there's exactly one changed field in an otherwise-identical block.
    """
    if old_content.strip() == new_content.strip():
        return "No changes"

    old_blocks = re.split(r'(?m)^##\s+', old_content)
    new_blocks = re.split(r'(?m)^##\s+', new_content)

    changes: List[str] = []
    if old_blocks[0].strip() != new_blocks[0].strip():
        changes.append("title/purpose changed")

    for i in range(1, max(len(old_blocks), len(new_blocks))):
        ob = old_blocks[i] if i < len(old_blocks) else None
        nb = new_blocks[i] if i < len(new_blocks) else None
        if ob is None:
            changes.append(f"{nb.splitlines()[0].strip()} added")
            continue
        if nb is None:
            changes.append(f"{ob.splitlines()[0].strip()} removed")
            continue
        if ob.strip() == nb.strip():
            continue
        name = ob.splitlines()[0].strip()
        of = re.split(r'(?m)^###\s+', ob)
        nf = re.split(r'(?m)^###\s+', nb)
        changed_fields = []
        for j in range(1, max(len(of), len(nf))):
            ofj = of[j] if j < len(of) else ""
            nfj = nf[j] if j < len(nf) else ""
            if ofj.strip() != nfj.strip():
                changed_fields.append((nfj or ofj).splitlines()[0].strip())
        if len(changed_fields) == 1:
            changes.append(f"{name}: {changed_fields[0]} changed")
        else:
            changes.append(f"{name} changed")

    if not changes:
        return "Minor formatting changes"
    if len(changes) > 3:
        return f"{len(changes)} sections changed"
    return "; ".join(changes)


def strip_outcome_sections(content: str) -> str:
    """
    Return content with the Outcome/Execution-Output sections (and any
    "Outcome (Run N)" re-run sections) removed — just the narrative +
    Command Sequence. Shared by fork(), save_as(), and "mark as template",
    since none of those should carry execution history forward.
    """
    return re.sub(
        r'\n\n---\n\n## Outcome\b.*',
        '',
        content,
        flags=re.DOTALL,
    ).rstrip()


# ---------------------------------------------------------------------------
# DocumentManager
# ---------------------------------------------------------------------------

class DocumentManager:
    """Manages Plan Document files across inbox / outbox / trash folders."""

    def __init__(self) -> None:
        self._paths = _load_paths()
        for p in self._paths.values():
            p.mkdir(parents=True, exist_ok=True)
        self._migrate_archived_to_trash()

    def _migrate_archived_to_trash(self) -> None:
        """
        One-time migration: the old "archived/" folder (dead code — never read
        by any endpoint or UI) is superseded by "trash/" as of the lifecycle
        redesign. If an old archived/ directory exists alongside the configured
        base and has files trash/ doesn't already have, move them over.
        """
        old_dir = self._paths["trash"].parent / "archived"
        if old_dir == self._paths["trash"] or not old_dir.is_dir():
            return
        moved = 0
        for md in old_dir.glob("*.md"):
            dest = self._paths["trash"] / md.name
            if not dest.exists():
                md.rename(dest)
                moved += 1
        if moved:
            logger.info(f"DocumentManager: migrated {moved} document(s) from archived/ to trash/")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, title: str, content: str) -> str:
        """
        Write a new plan document to inbox/.

        Returns the doc_id (filename stem) for subsequent operations.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        doc_id = f"{ts}_{_slug(title)}"
        path = self._paths["inbox"] / f"{doc_id}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(f"DocumentManager: created {path}")
        return doc_id

    def import_document(self, content: str, title: Optional[str] = None) -> str:
        """
        Import externally-written Dr.Egeria/LGCI markdown as a new managed plan
        in inbox/, exactly like a generated plan.

        Detects two shapes:
          - Already LGCI-structured ("## Command Sequence" header present) —
            imported as-is (an H1 title is added if one isn't already present).
          - Bare Dr.Egeria command file (just "## CommandName" blocks, no
            narrative) — wrapped with a synthesized title and an empty
            "## Command Sequence" header, so it conforms to what
            _extract_command_section() expects for validate/execute.

        Returns the new doc_id.
        """
        content = content.strip()
        if not content:
            raise ValueError("Cannot import empty content")

        has_command_sequence = bool(
            re.search(r'^##\s+Command Sequence\s*$', content, re.MULTILINE)
        )

        if has_command_sequence:
            existing_title = None
            for line in content.splitlines():
                if line.strip().startswith("# "):
                    existing_title = line.strip()[2:].strip()
                    break
            final_title = title or existing_title or "Imported Plan"
            final_content = content if existing_title else f"# {final_title}\n\n{content}"
        else:
            final_title = title or self._derive_title_from_commands(content) or "Imported Plan"
            final_content = (
                f"# {final_title}\n"
                f"**Imported:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"## Command Sequence\n\n"
                f"{content}\n"
            )

        doc_id = self.create(final_title, final_content)
        logger.info(f"DocumentManager: imported external document as {doc_id!r}")
        return doc_id

    @staticmethod
    def _derive_title_from_commands(content: str) -> Optional[str]:
        """Best-effort title for a bare command file: first Display Name, else first command verb."""
        m = re.search(r'^###\s+Display Name\s*\n(.+)$', content, re.MULTILINE)
        if m:
            return m.group(1).strip()
        m = re.search(r'^##\s+(.+)$', content, re.MULTILINE)
        if m:
            return m.group(1).strip()
        return None

    def load(self, doc_id: str, include_trash: bool = False) -> Optional[str]:
        """
        Load a plan document by doc_id from inbox or outbox (the "live" folders).

        Trash is excluded by default — a trashed document should not be silently
        usable by validate/execute/update. Pass include_trash=True for UI lookups
        that need to detect and surface a trashed document (e.g. the Editor's
        "this plan was deleted" banner).

        Returns the markdown content, or None if not found.
        """
        folders = ("inbox", "outbox", "trash") if include_trash else ("inbox", "outbox")
        for folder in folders:
            path = self._paths[folder] / f"{doc_id}.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        logger.warning(f"DocumentManager: doc_id {doc_id!r} not found")
        return None

    def load_outbox(self, doc_id: str) -> Optional[str]:
        """Load a plan document from the outbox only."""
        path = self._paths["outbox"] / f"{doc_id}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def update(self, doc_id: str, content: str, edited_by: Optional[str] = None) -> bool:
        """
        Overwrite a plan document in place (inbox only — executed docs are immutable).

        Saves a versioned backup to versions/ before overwriting. When edited_by
        is given, stamps the document header's "Last edited"/"Last edited by"
        fields with the current time and that user — see touch_edit_header().
        Pass edited_by=None for internal/automated rewrites (e.g. refreshing
        resolved values post-execution) that aren't a user-initiated edit.
        Returns True on success.
        """
        path = self._paths["inbox"] / f"{doc_id}.md"
        if not path.exists():
            logger.warning(f"DocumentManager.update: {doc_id!r} not in inbox")
            return False
        if edited_by:
            content = touch_edit_header(content, edited_by)
        self._save_version(doc_id, path.read_text(encoding="utf-8"), new_content=content)
        path.write_text(content, encoding="utf-8")
        logger.info(f"DocumentManager: updated {path}")
        return True

    def _save_version(self, doc_id: str, content: str, new_content: Optional[str] = None) -> None:
        """
        Write a timestamped backup of doc_id to versions/.

        new_content, when given, is what content is about to be replaced
        with — used to compute a short, best-effort "what changed" note
        (describe_changes()) stored as a leading HTML comment in the version
        file. Omit it when there's nothing meaningful to diff against (e.g.
        backing up before a delete).
        """
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ver_path = self._paths["versions"] / f"{original_doc_id}_v{ts}.md"
        try:
            final = content
            if new_content is not None:
                note = describe_changes(content, new_content)
                final = f"<!-- version_note: {note} -->\n{content}"
            ver_path.write_text(final, encoding="utf-8")
            logger.debug(f"DocumentManager: saved version {ver_path.name}")
        except Exception as exc:
            logger.warning(f"DocumentManager: version save failed: {exc}")

    def list_versions(self, doc_id: str) -> List[Dict[str, str]]:
        """Return version metadata for a given doc_id, newest first."""
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        versions_dir = self._paths["versions"]
        entries = []
        for md in sorted(versions_dir.glob(f"{original_doc_id}_v*.md"), reverse=True):
            # Extract the timestamp portion from the filename stem
            stem = md.stem  # e.g. "20260614_165841_..._v20260614_170122"
            ts_part = stem.rsplit("_v", 1)[-1] if "_v" in stem else ""
            description = ""
            try:
                m = _VERSION_NOTE_RE.match(md.read_text(encoding="utf-8"))
                if m:
                    description = m.group(1)
            except Exception:
                pass
            entries.append({
                "version_file": md.name,
                "timestamp": ts_part,
                "path": str(md),
                "description": description,
            })
        return entries

    def load_version(self, doc_id: str, version_file: str) -> Optional[str]:
        """Load content from a specific version file (the version_note comment, if any, stripped)."""
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        ver_path = self._paths["versions"] / version_file
        if ver_path.exists() and ver_path.stem.startswith(original_doc_id):
            content = ver_path.read_text(encoding="utf-8")
            return _VERSION_NOTE_RE.sub('', content, count=1)
        logger.warning(f"DocumentManager.load_version: {version_file!r} not found or wrong doc_id")
        return None

    def restore_version(self, doc_id: str, version_file: str) -> bool:
        """
        Restore a version to inbox, overwriting any existing inbox/outbox/trash copy.

        Whatever currently exists for this doc_id (in any folder) is saved as a
        version first. Returns True on success.
        """
        content = self.load_version(doc_id, version_file)
        if content is None:
            return False

        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        inbox_path = self._paths["inbox"] / f"{original_doc_id}.md"

        # Save whatever currently exists as a version before overwriting, and
        # remove it from wherever it was living (inbox/outbox/trash) — restoring
        # a version always lands the document back in inbox.
        for folder in ("inbox", "outbox", "trash"):
            for name in (doc_id, original_doc_id):
                existing = self._paths[folder] / f"{name}.md"
                if existing.exists():
                    self._save_version(name, existing.read_text(encoding="utf-8"), new_content=content)
                    existing.unlink()

        inbox_path.write_text(content, encoding="utf-8")
        logger.info(f"DocumentManager: restored {version_file} to inbox as {original_doc_id}")
        return True

    def fork(self, doc_id: str, new_title: str, version_file: Optional[str] = None) -> str:
        """
        Create a new, independent PlanDocument seeded from doc_id's current
        content (or a specific prior version if version_file is given).

        The Outcome/Execution-Output sections are stripped (a fork hasn't been
        executed yet) and replaced with a "## Known Objects" appendix listing
        the Qualified Name and GUID of anything the source plan successfully
        created, parsed from its Command Results table — so the new plan's
        commands can reference these objects directly without retyping or a
        live Egeria round-trip. Editing the fork never touches the source's
        history.

        Returns the new doc_id.
        """
        if version_file:
            source_content = self.load_version(doc_id, version_file)
            lineage_ts = version_file.rsplit("_v", 1)[-1].replace(".md", "")
        else:
            source_content = self.load(doc_id, include_trash=True)
            lineage_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if source_content is None:
            raise ValueError(
                f"Could not load source content for fork "
                f"(doc_id={doc_id!r}, version_file={version_file!r})"
            )

        known_objects = _parse_known_objects(source_content)

        # Keep narrative + Command Sequence; drop everything from the Outcome separator onward
        stripped = strip_outcome_sections(source_content)

        appendix = f"\n\n**Forked from:** `{doc_id}` @ {lineage_ts}\n"
        if known_objects:
            rows = "\n".join(
                f"| {o['command']} | {o['qualified_name']} | {o['guid']} |"
                for o in known_objects
            )
            appendix += (
                "\n## Known Objects (from forked plan)\n\n"
                "| Command | Qualified Name | GUID |\n"
                "|---------|----------------|------|\n"
                f"{rows}\n"
            )

        new_content = _replace_title(stripped, new_title) + appendix
        new_doc_id = self.create(new_title, new_content)
        logger.info(
            f"DocumentManager: forked {doc_id!r} (version={version_file}) -> {new_doc_id!r} "
            f"({len(known_objects)} known object(s) carried forward)"
        )
        return new_doc_id

    def save_as(self, doc_id: str, new_title: str, version_file: Optional[str] = None) -> str:
        """
        Save doc_id's current content (or a specific prior version) as a new,
        independent plan under new_title — the specification only, with no
        history: no Outcome/Execution-Output sections, no Known Objects
        appendix, no "Forked from" lineage note. Unlike fork(), the result
        looks exactly like a freshly-authored plan.

        Returns the new doc_id.
        """
        if version_file:
            source_content = self.load_version(doc_id, version_file)
        else:
            source_content = self.load(doc_id, include_trash=True)

        if source_content is None:
            raise ValueError(
                f"Could not load source content for save_as "
                f"(doc_id={doc_id!r}, version_file={version_file!r})"
            )

        stripped = strip_outcome_sections(source_content)

        new_content = _replace_title(stripped, new_title)
        new_doc_id = self.create(new_title, new_content)
        logger.info(f"DocumentManager: saved {doc_id!r} as new plan {new_doc_id!r} (no history carried)")
        return new_doc_id

    def move_to_outbox(self, doc_id: str, outcome_content: str) -> Optional[str]:
        """
        Append outcome_content to the plan document and move it to outbox/.

        Returns the new outbox doc_id on success, or None on failure.
        """
        inbox_path = self._paths["inbox"] / f"{doc_id}.md"
        if not inbox_path.exists():
            logger.warning(f"DocumentManager.move_to_outbox: {doc_id!r} not in inbox")
            return None
        original = inbox_path.read_text(encoding="utf-8")
        final = original.rstrip() + "\n\n---\n\n" + outcome_content.strip() + "\n"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        outbox_doc_id = f"{doc_id}_executed_{ts}"
        outbox_path = self._paths["outbox"] / f"{outbox_doc_id}.md"
        outbox_path.write_text(final, encoding="utf-8")
        inbox_path.unlink()
        logger.info(f"DocumentManager: moved {doc_id} to outbox as {outbox_doc_id}")
        return outbox_doc_id

    def append_rerun_outcome(self, doc_id: str, outcome_content: str) -> bool:
        """
        Append a new Outcome section to a document that's already in outbox/,
        for "Re-run Now" — executing directly from outbox without an inbox
        detour. The document stays in outbox; it never touches inbox.

        Versions the pre-run outbox content first. The first-ever outcome
        section is left as "## Outcome"; this method's job is only invoked
        for the second and later runs, so the new section is always
        "## Outcome (Run N)" where N counts existing "## Outcome" headers + 1.
        """
        outbox_path = self._paths["outbox"] / f"{doc_id}.md"
        if not outbox_path.exists():
            logger.warning(f"DocumentManager.append_rerun_outcome: {doc_id!r} not in outbox")
            return False

        original = outbox_path.read_text(encoding="utf-8")

        run_number = len(re.findall(r'^##\s+Outcome\b', original, re.MULTILINE)) + 1
        section = outcome_content.strip()
        if run_number > 1:
            section = re.sub(
                r'^##\s+Outcome\b.*$',
                f"## Outcome (Run {run_number})",
                section,
                count=1,
                flags=re.MULTILINE,
            )

        final = original.rstrip() + "\n\n---\n\n" + section + "\n"
        self._save_version(doc_id, original, new_content=final)
        outbox_path.write_text(final, encoding="utf-8")
        logger.info(f"DocumentManager: appended re-run outcome (run {run_number}) to {doc_id}")
        return True

    def move_to_inbox(self, doc_id: str) -> Optional[str]:
        """
        Move a plan document from outbox back to inbox, stripping the outcome section.

        Returns the new inbox doc_id on success, or None on failure. Fails if the inbox
        already has a file with that name (would overwrite a different plan).
        """
        outbox_path = self._paths["outbox"] / f"{doc_id}.md"
        if not outbox_path.exists():
            logger.warning(f"DocumentManager.move_to_inbox: {doc_id!r} not in outbox")
            return None
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        inbox_path = self._paths["inbox"] / f"{original_doc_id}.md"
        if inbox_path.exists():
            logger.warning(f"DocumentManager.move_to_inbox: {original_doc_id!r} already exists in inbox")
            return None
        content = outbox_path.read_text(encoding="utf-8")
        # Strip the outcome section (everything from the separator before ## Outcome onward)
        stripped = strip_outcome_sections(content)
        self._save_version(original_doc_id, content, new_content=stripped + "\n")
        inbox_path.write_text(stripped + "\n", encoding="utf-8")
        outbox_path.unlink()
        logger.info(f"DocumentManager: moved {doc_id} from outbox back to inbox as {original_doc_id}")
        return original_doc_id

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_inbox(self) -> List[Dict[str, str]]:
        """Return metadata for all documents in inbox/, newest first."""
        return self._list_folder("inbox")

    def list_outbox(self) -> List[Dict[str, str]]:
        """Return metadata for all documents in outbox/, newest first."""
        return self._list_folder("outbox")

    def list_trash(self) -> List[Dict[str, str]]:
        """Return metadata for all documents in trash/, newest first."""
        return self._list_folder("trash")

    def delete(self, doc_id: str) -> bool:
        """
        Soft-delete: move a document from inbox or outbox to trash/ (whichever
        it's in). A version snapshot is saved first. Returns True if moved.

        This is reversible — see restore_from_trash(). If a document already
        exists in trash with this doc_id, it is overwritten (its own content
        was already versioned when it was first trashed).
        """
        for folder in ("inbox", "outbox"):
            path = self._paths[folder] / f"{doc_id}.md"
            if path.exists():
                content = path.read_text(encoding="utf-8")
                self._save_version(doc_id, content)
                trash_path = self._paths["trash"] / f"{doc_id}.md"
                trash_path.write_text(content, encoding="utf-8")
                path.unlink()
                logger.info(f"DocumentManager: moved {doc_id} to trash")
                return True
        return False

    def restore_from_trash(self, doc_id: str) -> bool:
        """
        Restore a document from trash/ back to its correct folder (outbox or inbox).
        A version snapshot of the trash copy is saved first.
        """
        trash_path = self._paths["trash"] / f"{doc_id}.md"
        if not trash_path.exists():
            logger.warning(f"DocumentManager.restore_from_trash: {doc_id!r} not in trash")
            return False
        dest_folder = "outbox" if "_executed_" in doc_id else "inbox"
        dest_path = self._paths[dest_folder] / f"{doc_id}.md"
        if dest_path.exists():
            logger.warning(f"DocumentManager.restore_from_trash: {doc_id!r} already exists in {dest_folder}")
            return False
        content = trash_path.read_text(encoding="utf-8")
        self._save_version(doc_id, content)
        dest_path.write_text(content, encoding="utf-8")
        trash_path.unlink()
        logger.info(f"DocumentManager: restored {doc_id} from trash to {dest_folder}")
        return True

    def purge(self, doc_id: str) -> bool:
        """
        Permanently delete a document from trash/. Does not touch versions/ —
        prior snapshots (including the one saved at delete time) remain
        available even after a purge.
        """
        trash_path = self._paths["trash"] / f"{doc_id}.md"
        if not trash_path.exists():
            logger.warning(f"DocumentManager.purge: {doc_id!r} not in trash")
            return False
        trash_path.unlink()
        logger.info(f"DocumentManager: purged {doc_id} from trash")
        return True

    def _list_folder(self, folder: str) -> List[Dict[str, str]]:
        folder_path = self._paths[folder]
        entries = []
        for md in sorted(folder_path.glob("*.md"), reverse=True):
            content = md.read_text(encoding="utf-8", errors="replace")
            title = self._extract_title(content)
            status = self._extract_status(content)
            entries.append({
                "doc_id": md.stem,
                "title": title,
                "status": status,
                "folder": folder,
                "path": str(md),
            })
        return entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_title(content: str) -> str:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                # Strip legacy "Data Management Plan: " prefix from older documents
                if title.lower().startswith("data management plan:"):
                    title = title[len("data management plan:"):].strip()
                return title
        return "(untitled)"

    @staticmethod
    def _extract_status(content: str) -> str:
        for line in content.splitlines():
            m = re.search(r"\*\*Status:\*\*\s*(\w+)", line)
            if m:
                return m.group(1)
        return "Draft"

    def inbox_path(self) -> Path:
        return self._paths["inbox"]

    def outbox_path(self) -> Path:
        return self._paths["outbox"]

    def trash_path(self) -> Path:
        return self._paths["trash"]

    def folder_of(self, doc_id: str) -> Optional[str]:
        """Return which folder (inbox/outbox/trash) currently holds doc_id, or None."""
        for folder in ("inbox", "outbox", "trash"):
            if (self._paths[folder] / f"{doc_id}.md").exists():
                return folder
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_doc_manager: Optional[DocumentManager] = None


def get_doc_manager() -> DocumentManager:
    global _doc_manager
    if _doc_manager is None:
        _doc_manager = DocumentManager()
    return _doc_manager
