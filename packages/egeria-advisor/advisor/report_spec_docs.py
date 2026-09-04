"""
ReportSpecDocumentManager — lifecycle management for Report Spec Documents (RSDs).

Folder layout:
  ~/egeria-reports/inbox/     — report specs (.md) awaiting run or editing
  ~/egeria-reports/outbox/    — executed report outputs (.md)
  ~/egeria-reports/trash/     — soft-deleted report specs/runs
  ~/egeria-reports/versions/  — immutable timestamped version snapshots
"""
from __future__ import annotations

import re
import os
import yaml
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from loguru import logger


def _load_paths() -> Dict[str, Path]:
    """Resolve report spec directory paths inside ~/egeria-reports/."""
    base = Path.home() / "egeria-reports"
    defaults = {
        "inbox":    base / "inbox",
        "outbox":   base / "outbox",
        "trash":    base / "trash",
        "versions": base / "versions",
    }
    return defaults


def _slug(title: str) -> str:
    """Convert a report title to a filesystem-safe slug."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:60].strip("_")


# ---------------------------------------------------------------------------
# Per-user namespacing — mirrors governance_docs.py's identical mechanism;
# see that module's docstring and docs/runtime-architecture-plan.md §4.
# ---------------------------------------------------------------------------

def _safe_user_id(user_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.@-]", "_", user_id)[:100]


def _user_paths(shared_paths: Dict[str, Path], user_id: str) -> Dict[str, Path]:
    base = shared_paths["inbox"].parent / "users" / _safe_user_id(user_id)
    paths = {
        "inbox":    base / "inbox",
        "outbox":   base / "outbox",
        "trash":    base / "trash",
        "versions": base / "versions",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def _list_namespaced_user_ids(shared_paths: Dict[str, Path]) -> List[str]:
    users_dir = shared_paths["inbox"].parent / "users"
    if not users_dir.is_dir():
        return []
    return sorted(p.name for p in users_dir.iterdir() if p.is_dir())


_CURATOR_ROLES = {"admin", "curator"}


def _is_curator_role(role: Optional[str]) -> bool:
    return (role or "").lower() in _CURATOR_ROLES


class ReportSpecDocumentManager:
    """Manages Report Spec Document files across inbox / outbox / trash folders.

    Namespacing works exactly like `governance_docs.DocumentManager` — see
    that class's docstring for the full explanation. In short: `create()`/
    `import_document()` take an optional `user_id` and write into that
    user's `users/{user_id}/...` tree; every doc_id-keyed method resolves
    doc_id across the shared root and every namespace (`_locate`), so the
    rest of the lifecycle (execute, retry, versions, ...) keeps working
    unchanged for a namespaced spec with no caller changes needed.
    """

    def __init__(self) -> None:
        self._paths = _load_paths()
        for p in self._paths.values():
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Namespace resolution
    # ------------------------------------------------------------------

    def _owner_of_root(self, root_paths: Dict[str, Path]) -> Optional[str]:
        if root_paths is self._paths:
            return None
        users_dir = self._paths["inbox"].parent / "users"
        try:
            rel = root_paths["inbox"].relative_to(users_dir)
            return rel.parts[0]
        except ValueError:
            return None

    def _all_roots(self) -> List[Dict[str, Path]]:
        roots = [self._paths]
        for uid in _list_namespaced_user_ids(self._paths):
            roots.append(_user_paths(self._paths, uid))
        return roots

    def _locate(self, doc_id: str, folders) -> Optional[tuple]:
        """Search shared then namespaced roots' given folders for doc_id.md.
        Returns (root_paths, folder, path) for the first match, or None."""
        for root_paths in self._all_roots():
            for folder in folders:
                p = root_paths[folder] / f"{doc_id}.md"
                if p.exists():
                    return root_paths, folder, p
        return None

    def _locate_runs(self, base_doc_id: str) -> Optional[tuple]:
        """Search every root's outbox for `{base_doc_id}_executed_*.md`.
        Returns (root_paths, newest_run_path) or None."""
        for root_paths in self._all_roots():
            runs = sorted(root_paths["outbox"].glob(f"{base_doc_id}_executed_*.md"), reverse=True)
            if runs:
                return root_paths, runs[0]
        return None

    @staticmethod
    def _visible(owner: Optional[str], requester_user_id: Optional[str],
                 requester_role: Optional[str]) -> bool:
        if owner is None:
            return True
        return owner == requester_user_id or _is_curator_role(requester_role)

    def create(self, title: str, content: str, user_id: Optional[str] = None) -> str:
        """Write a new report spec document to inbox/ — namespaced to
        user_id when given, else the shared root."""
        root_paths = _user_paths(self._paths, user_id) if user_id else self._paths
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        doc_id = f"report_{ts}_{_slug(title)}"
        path = root_paths["inbox"] / f"{doc_id}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(f"ReportSpecDocumentManager: created {path}")
        return doc_id

    def load(self, doc_id: str, include_trash: bool = False,
             requester_user_id: Optional[str] = None, requester_role: Optional[str] = None,
             enforce_ownership: bool = False) -> Optional[str]:
        """Load a report spec document by doc_id from inbox or outbox.

        See governance_docs.DocumentManager.load() for the enforce_ownership
        contract (404-shaped None for a namespaced doc that isn't the
        requester's own and the requester isn't a curator).
        """
        # 1. Exact match in inbox (any namespace)
        loc = self._locate(doc_id, ("inbox",))
        if loc is not None:
            root_paths, _folder, inbox_path = loc
            if enforce_ownership and not self._visible(
                self._owner_of_root(root_paths), requester_user_id, requester_role
            ):
                return None
            content = inbox_path.read_text(encoding="utf-8")
            try:
                from advisor.report_spec_parser import parse_report_spec_markdown, register_report_spec
                spec = parse_report_spec_markdown(content)
                register_report_spec(doc_id, spec)
            except Exception:
                pass
            return content

        # 2. Latest executed run in any namespace's outbox (executing never
        #    unlinks the spec from inbox — see move_to_outbox — but a caller
        #    may still ask for a doc_id that was later purged from inbox)
        run_loc = self._locate_runs(doc_id)
        if run_loc is not None:
            root_paths, run_path = run_loc
            if enforce_ownership and not self._visible(
                self._owner_of_root(root_paths), requester_user_id, requester_role
            ):
                return None
            content = run_path.read_text(encoding="utf-8")
            stripped = re.sub(r'\n\n---\n\n## Outcome\b.*', '', content, flags=re.DOTALL)
            return stripped.rstrip() + "\n"

        # 3. Fallback to other folders (e.g. trash, or outbox with exact name)
        folders = ("outbox", "trash") if include_trash else ("outbox",)
        loc = self._locate(doc_id, folders)
        if loc is not None:
            root_paths, _folder, path = loc
            if enforce_ownership and not self._visible(
                self._owner_of_root(root_paths), requester_user_id, requester_role
            ):
                return None
            return path.read_text(encoding="utf-8")

        logger.warning(f"ReportSpecDocumentManager: doc_id {doc_id!r} not found")
        return None

    def load_outbox(self, doc_id: str) -> Optional[str]:
        """Load an executed report document from the outbox only (any namespace)."""
        loc = self._locate(doc_id, ("outbox",))
        return loc[2].read_text(encoding="utf-8") if loc else None

    def import_document(self, content: str, title: Optional[str] = None,
                         user_id: Optional[str] = None) -> str:
        """
        Import externally-written Report Spec markdown as a new managed spec
        in inbox/, exactly like a generated report spec.

        Validates the content parses as a Report Spec (must contain a
        'Create Report Spec' command — see parse_report_spec_markdown) so a
        malformed import fails fast instead of silently producing a spec
        that can't be run. Mirrors DocumentManager.import_document().

        Returns the new doc_id.
        """
        content = content.strip()
        if not content:
            raise ValueError("Cannot import empty content")

        from advisor.report_spec_parser import parse_report_spec_markdown
        spec = parse_report_spec_markdown(content)  # raises ValueError if invalid

        final_title = title or spec.heading or "Imported Report Spec"
        doc_id = self.create(final_title, content, user_id=user_id)
        logger.info(f"ReportSpecDocumentManager: imported external document as {doc_id!r}")
        return doc_id

    def update(self, doc_id: str, content: str) -> bool:
        """Overwrite a report spec document in place (inbox only)."""
        loc = self._locate(doc_id, ("inbox",))
        if loc is None:
            logger.warning(f"ReportSpecDocumentManager.update: {doc_id!r} not in inbox")
            return False
        root_paths, _folder, path = loc
        self._save_version(doc_id, path.read_text(encoding="utf-8"), root_paths=root_paths)
        path.write_text(content, encoding="utf-8")
        logger.info(f"ReportSpecDocumentManager: updated {path}")
        return True

    def _save_version(self, doc_id: str, content: str,
                       root_paths: Optional[Dict[str, Path]] = None) -> None:
        """Write a timestamped backup of doc_id to versions/. root_paths
        defaults to the shared root; callers that resolved a namespaced
        document via `_locate` pass its root_paths through."""
        root_paths = root_paths or self._paths
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ver_path = root_paths["versions"] / f"{original_doc_id}_v{ts}.md"
        try:
            ver_path.write_text(content, encoding="utf-8")
            logger.debug(f"ReportSpecDocumentManager: saved version {ver_path.name}")
        except Exception as exc:
            logger.warning(f"ReportSpecDocumentManager: version save failed: {exc}")

    def _versions_root_for(self, doc_id: str) -> Dict[str, Path]:
        loc = self._locate(doc_id, ("inbox", "outbox", "trash"))
        return loc[0] if loc else self._paths

    def list_versions(self, doc_id: str) -> List[Dict[str, str]]:
        """Return version metadata for a given doc_id, newest first."""
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        versions_dir = self._versions_root_for(doc_id)["versions"]
        entries = []
        for md in sorted(versions_dir.glob(f"{original_doc_id}_v*.md"), reverse=True):
            stem = md.stem
            ts_part = stem.rsplit("_v", 1)[-1] if "_v" in stem else ""
            entries.append({
                "version_file": md.name,
                "timestamp": ts_part,
                "path": str(md),
            })
        return entries

    def load_version(self, doc_id: str, version_file: str) -> Optional[str]:
        """Load content from a specific version file."""
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        ver_path = self._versions_root_for(doc_id)["versions"] / version_file
        if ver_path.exists() and ver_path.stem.startswith(original_doc_id):
            return ver_path.read_text(encoding="utf-8")
        logger.warning(f"ReportSpecDocumentManager.load_version: {version_file!r} not found")
        return None

    def restore_version(self, doc_id: str, version_file: str) -> bool:
        """Restore a version to inbox, overwriting any existing copy."""
        root_paths = self._versions_root_for(doc_id)
        content = self.load_version(doc_id, version_file)
        if content is None:
            return False

        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        inbox_path = root_paths["inbox"] / f"{original_doc_id}.md"

        for folder in ("inbox", "outbox", "trash"):
            for name in (doc_id, original_doc_id):
                existing = root_paths[folder] / f"{name}.md"
                if existing.exists():
                    self._save_version(name, existing.read_text(encoding="utf-8"), root_paths=root_paths)
                    existing.unlink()

        inbox_path.write_text(content, encoding="utf-8")
        logger.info(f"ReportSpecDocumentManager: restored {version_file} to inbox as {original_doc_id}")
        return True

    def move_to_outbox(self, doc_id: str, outcome_content: str) -> Optional[str]:
        """Write a result snapshot to outbox/ with outcomes appended.

        The spec remains in inbox/ (the catalog) — it is a persistent view definition,
        not a one-time document.  Result snapshots are separate outbox artifacts.
        """
        base_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        loc = self._locate(base_doc_id, ("inbox",))

        if loc is not None:
            root_paths, _folder, inbox_path = loc
            original = inbox_path.read_text(encoding="utf-8")
        else:
            original = self.load(base_doc_id)
            if not original:
                logger.warning(f"ReportSpecDocumentManager.move_to_outbox: could not load spec for {base_doc_id!r}")
                return None
            root_paths = self._versions_root_for(base_doc_id)

        final = original.rstrip() + "\n\n---\n\n" + outcome_content.strip() + "\n"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_doc_id = f"{base_doc_id}_executed_{ts}"
        outbox_path = root_paths["outbox"] / f"{result_doc_id}.md"
        outbox_path.write_text(final, encoding="utf-8")
        logger.info(f"ReportSpecDocumentManager: result snapshot {result_doc_id} saved; spec remains in catalog")
        return result_doc_id

    def move_to_inbox(self, doc_id: str) -> Optional[str]:
        """Move an executed report document back to inbox, stripping the outcome section."""
        loc = self._locate(doc_id, ("outbox",))
        if loc is None:
            logger.warning(f"ReportSpecDocumentManager.move_to_inbox: {doc_id!r} not in outbox")
            return None
        root_paths, _folder, outbox_path = loc
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        inbox_path = root_paths["inbox"] / f"{original_doc_id}.md"
        if inbox_path.exists():
            logger.warning(f"ReportSpecDocumentManager.move_to_inbox: {original_doc_id!r} already exists in inbox")
            return None
        content = outbox_path.read_text(encoding="utf-8")
        stripped = re.sub(
            r'\n\n---\n\n## Outcome\b.*',
            '',
            content,
            flags=re.DOTALL,
        )
        self._save_version(original_doc_id, content, root_paths=root_paths)
        inbox_path.write_text(stripped.rstrip() + "\n", encoding="utf-8")
        outbox_path.unlink()
        logger.info(f"ReportSpecDocumentManager: moved {doc_id} back to inbox as {original_doc_id}")
        return original_doc_id

    def delete(self, doc_id: str) -> bool:
        """Soft-delete: move document from inbox/outbox to trash/."""
        loc = self._locate(doc_id, ("inbox", "outbox"))
        if loc is None:
            return False
        root_paths, _folder, path = loc
        content = path.read_text(encoding="utf-8")
        self._save_version(doc_id, content, root_paths=root_paths)
        trash_path = root_paths["trash"] / f"{doc_id}.md"
        trash_path.write_text(content, encoding="utf-8")
        path.unlink()
        logger.info(f"ReportSpecDocumentManager: moved {doc_id} to trash")
        return True

    def restore_from_trash(self, doc_id: str) -> bool:
        """Restore a document from trash/ back to inbox/outbox."""
        loc = self._locate(doc_id, ("trash",))
        if loc is None:
            logger.warning(f"ReportSpecDocumentManager.restore_from_trash: {doc_id!r} not in trash")
            return False
        root_paths, _folder, trash_path = loc
        dest_folder = "outbox" if "_executed_" in doc_id else "inbox"
        dest_path = root_paths[dest_folder] / f"{doc_id}.md"
        if dest_path.exists():
            logger.warning(f"ReportSpecDocumentManager.restore_from_trash: {doc_id!r} already exists in {dest_folder}")
            return False
        content = trash_path.read_text(encoding="utf-8")
        self._save_version(doc_id, content, root_paths=root_paths)
        dest_path.write_text(content, encoding="utf-8")
        trash_path.unlink()
        logger.info(f"ReportSpecDocumentManager: restored {doc_id} from trash to {dest_folder}")
        return True

    def purge(self, doc_id: str) -> bool:
        """Permanently delete a document from trash/."""
        loc = self._locate(doc_id, ("trash",))
        if loc is None:
            return False
        loc[2].unlink()
        return True

    def list_inbox(self, requester_user_id: Optional[str] = None,
                    requester_role: Optional[str] = None) -> List[Dict[str, str]]:
        """Return list of inbox report specs, auto-parsing and registering them.

        No requester_user_id: shared root only (unchanged behaviour). With
        one: shared + the requester's own namespace, plus every namespace
        for a curator role — each entry tagged "owner" (None for shared).
        """
        roots = [(None, self._paths)]
        if requester_user_id is not None:
            for uid in _list_namespaced_user_ids(self._paths):
                if self._visible(uid, requester_user_id, requester_role):
                    roots.append((uid, _user_paths(self._paths, uid)))
        entries = []
        for owner, root_paths in roots:
            for md in sorted(root_paths["inbox"].glob("*.md"), reverse=True):
                content = md.read_text(encoding="utf-8", errors="replace")
                try:
                    from advisor.report_spec_parser import parse_report_spec_markdown, register_report_spec
                    spec = parse_report_spec_markdown(content)
                    register_report_spec(md.stem, spec)
                except Exception as e:
                    logger.error(f"Failed to auto-register report spec {md.name}: {e}")

                title = self._extract_title(content)
                status = self._extract_status(content)
                entry = {
                    "doc_id": md.stem,
                    "title": title,
                    "status": status,
                    "folder": "inbox",
                    "path": str(md),
                }
                if requester_user_id is not None:
                    entry["owner"] = owner
                entries.append(entry)
        return entries

    def list_outbox(self, requester_user_id: Optional[str] = None,
                     requester_role: Optional[str] = None) -> List[Dict[str, str]]:
        """Return list of executed reports. See list_inbox() for requester args."""
        return self._list_folder("outbox", requester_user_id, requester_role)

    def list_trash(self, requester_user_id: Optional[str] = None,
                    requester_role: Optional[str] = None) -> List[Dict[str, str]]:
        """Return list of trashed reports. See list_inbox() for requester args."""
        return self._list_folder("trash", requester_user_id, requester_role)

    def folder_of(self, doc_id: str) -> Optional[str]:
        """Return folder containing doc_id, searching every namespace."""
        loc = self._locate(doc_id, ("inbox", "outbox", "trash"))
        if loc is not None:
            return loc[1]

        base_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        loc = self._locate(base_doc_id, ("inbox", "outbox", "trash"))
        if loc is not None:
            return loc[1]
        run_loc = self._locate_runs(base_doc_id)
        if run_loc is not None:
            return "outbox"
        return None

    def _list_folder(self, folder: str, requester_user_id: Optional[str] = None,
                      requester_role: Optional[str] = None) -> List[Dict[str, str]]:
        roots = [(None, self._paths)]
        if requester_user_id is not None:
            for uid in _list_namespaced_user_ids(self._paths):
                if self._visible(uid, requester_user_id, requester_role):
                    roots.append((uid, _user_paths(self._paths, uid)))
        entries = []
        for owner, root_paths in roots:
            folder_path = root_paths[folder]
            for md in sorted(folder_path.glob("*.md"), reverse=True):
                content = md.read_text(encoding="utf-8", errors="replace")
                title = self._extract_title(content)
                status = self._extract_status(content)
                entry = {
                    "doc_id": md.stem,
                    "title": title,
                    "status": status,
                    "folder": folder,
                    "path": str(md),
                }
                if requester_user_id is not None:
                    entry["owner"] = owner
                entries.append(entry)
        return entries

    @staticmethod
    def _extract_title(content: str) -> str:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return "(untitled)"

    @staticmethod
    def _extract_status(content: str) -> str:
        for line in content.splitlines():
            m = re.search(r"\*\*Status:\*\*\s*(\w+)", line)
            if m:
                return m.group(1)
        return "Draft"


_report_spec_doc_manager: Optional[ReportSpecDocumentManager] = None


def get_report_spec_doc_manager() -> ReportSpecDocumentManager:
    global _report_spec_doc_manager
    if _report_spec_doc_manager is None:
        _report_spec_doc_manager = ReportSpecDocumentManager()
    return _report_spec_doc_manager
