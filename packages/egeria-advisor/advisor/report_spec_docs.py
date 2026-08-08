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


class ReportSpecDocumentManager:
    """Manages Report Spec Document files across inbox / outbox / trash folders."""

    def __init__(self) -> None:
        self._paths = _load_paths()
        for p in self._paths.values():
            p.mkdir(parents=True, exist_ok=True)

    def create(self, title: str, content: str) -> str:
        """Write a new report spec document to inbox/."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        doc_id = f"report_{ts}_{_slug(title)}"
        path = self._paths["inbox"] / f"{doc_id}.md"
        path.write_text(content, encoding="utf-8")
        logger.info(f"ReportSpecDocumentManager: created {path}")
        return doc_id

    def load(self, doc_id: str, include_trash: bool = False) -> Optional[str]:
        """Load a report spec document by doc_id from inbox or outbox."""
        # 1. Try exact match in inbox
        inbox_path = self._paths["inbox"] / f"{doc_id}.md"
        if inbox_path.exists():
            content = inbox_path.read_text(encoding="utf-8")
            try:
                from advisor.report_spec_parser import parse_report_spec_markdown, register_report_spec
                spec = parse_report_spec_markdown(content)
                register_report_spec(doc_id, spec)
            except Exception:
                pass
            return content

        # 2. Try matching latest executed run in outbox (since executing unlinks from inbox)
        outbox_dir = self._paths["outbox"]
        runs = sorted(outbox_dir.glob(f"{doc_id}_executed_*.md"), reverse=True)
        if runs:
            content = runs[0].read_text(encoding="utf-8")
            # Strip outcome section
            stripped = re.sub(
                r'\n\n---\n\n## Outcome\b.*',
                '',
                content,
                flags=re.DOTALL,
            )
            return stripped.rstrip() + "\n"

        # 3. Fallback to other folders (e.g. trash or outbox with exact name)
        folders = ("outbox", "trash") if include_trash else ("outbox",)
        for folder in folders:
            path = self._paths[folder] / f"{doc_id}.md"
            if path.exists():
                return path.read_text(encoding="utf-8")

        logger.warning(f"ReportSpecDocumentManager: doc_id {doc_id!r} not found")
        return None

    def load_outbox(self, doc_id: str) -> Optional[str]:
        """Load an executed report document from the outbox only."""
        path = self._paths["outbox"] / f"{doc_id}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def import_document(self, content: str, title: Optional[str] = None) -> str:
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
        doc_id = self.create(final_title, content)
        logger.info(f"ReportSpecDocumentManager: imported external document as {doc_id!r}")
        return doc_id

    def update(self, doc_id: str, content: str) -> bool:
        """Overwrite a report spec document in place (inbox only)."""
        path = self._paths["inbox"] / f"{doc_id}.md"
        if not path.exists():
            logger.warning(f"ReportSpecDocumentManager.update: {doc_id!r} not in inbox")
            return False
        self._save_version(doc_id, path.read_text(encoding="utf-8"))
        path.write_text(content, encoding="utf-8")
        logger.info(f"ReportSpecDocumentManager: updated {path}")
        return True

    def _save_version(self, doc_id: str, content: str) -> None:
        """Write a timestamped backup of doc_id to versions/."""
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ver_path = self._paths["versions"] / f"{original_doc_id}_v{ts}.md"
        try:
            ver_path.write_text(content, encoding="utf-8")
            logger.debug(f"ReportSpecDocumentManager: saved version {ver_path.name}")
        except Exception as exc:
            logger.warning(f"ReportSpecDocumentManager: version save failed: {exc}")

    def list_versions(self, doc_id: str) -> List[Dict[str, str]]:
        """Return version metadata for a given doc_id, newest first."""
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        versions_dir = self._paths["versions"]
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
        ver_path = self._paths["versions"] / version_file
        if ver_path.exists() and ver_path.stem.startswith(original_doc_id):
            return ver_path.read_text(encoding="utf-8")
        logger.warning(f"ReportSpecDocumentManager.load_version: {version_file!r} not found")
        return None

    def restore_version(self, doc_id: str, version_file: str) -> bool:
        """Restore a version to inbox, overwriting any existing copy."""
        content = self.load_version(doc_id, version_file)
        if content is None:
            return False

        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        inbox_path = self._paths["inbox"] / f"{original_doc_id}.md"

        for folder in ("inbox", "outbox", "trash"):
            for name in (doc_id, original_doc_id):
                existing = self._paths[folder] / f"{name}.md"
                if existing.exists():
                    self._save_version(name, existing.read_text(encoding="utf-8"))
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
        inbox_path = self._paths["inbox"] / f"{base_doc_id}.md"

        if inbox_path.exists():
            original = inbox_path.read_text(encoding="utf-8")
        else:
            original = self.load(base_doc_id)
            if not original:
                logger.warning(f"ReportSpecDocumentManager.move_to_outbox: could not load spec for {base_doc_id!r}")
                return None

        final = original.rstrip() + "\n\n---\n\n" + outcome_content.strip() + "\n"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_doc_id = f"{base_doc_id}_executed_{ts}"
        outbox_path = self._paths["outbox"] / f"{result_doc_id}.md"
        outbox_path.write_text(final, encoding="utf-8")
        logger.info(f"ReportSpecDocumentManager: result snapshot {result_doc_id} saved; spec remains in catalog")
        return result_doc_id

    def move_to_inbox(self, doc_id: str) -> Optional[str]:
        """Move an executed report document back to inbox, stripping the outcome section."""
        outbox_path = self._paths["outbox"] / f"{doc_id}.md"
        if not outbox_path.exists():
            logger.warning(f"ReportSpecDocumentManager.move_to_inbox: {doc_id!r} not in outbox")
            return None
        original_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        inbox_path = self._paths["inbox"] / f"{original_doc_id}.md"
        if inbox_path.exists():
            logger.warning(f"ReportSpecDocumentManager.move_to_inbox: {original_doc_id!r} already exists in inbox")
            return None
        content = outbox_path.read_text(encoding="utf-8")
        # Strip outcome section
        stripped = re.sub(
            r'\n\n---\n\n## Outcome\b.*',
            '',
            content,
            flags=re.DOTALL,
        )
        self._save_version(original_doc_id, content)
        inbox_path.write_text(stripped.rstrip() + "\n", encoding="utf-8")
        outbox_path.unlink()
        logger.info(f"ReportSpecDocumentManager: moved {doc_id} back to inbox as {original_doc_id}")
        return original_doc_id

    def delete(self, doc_id: str) -> bool:
        """Soft-delete: move document from inbox/outbox to trash/."""
        for folder in ("inbox", "outbox"):
            path = self._paths[folder] / f"{doc_id}.md"
            if path.exists():
                content = path.read_text(encoding="utf-8")
                self._save_version(doc_id, content)
                trash_path = self._paths["trash"] / f"{doc_id}.md"
                trash_path.write_text(content, encoding="utf-8")
                path.unlink()
                logger.info(f"ReportSpecDocumentManager: moved {doc_id} to trash")
                return True
        return False

    def restore_from_trash(self, doc_id: str) -> bool:
        """Restore a document from trash/ back to inbox/outbox."""
        trash_path = self._paths["trash"] / f"{doc_id}.md"
        if not trash_path.exists():
            logger.warning(f"ReportSpecDocumentManager.restore_from_trash: {doc_id!r} not in trash")
            return False
        dest_folder = "outbox" if "_executed_" in doc_id else "inbox"
        dest_path = self._paths[dest_folder] / f"{doc_id}.md"
        if dest_path.exists():
            logger.warning(f"ReportSpecDocumentManager.restore_from_trash: {doc_id!r} already exists in {dest_folder}")
            return False
        content = trash_path.read_text(encoding="utf-8")
        self._save_version(doc_id, content)
        dest_path.write_text(content, encoding="utf-8")
        trash_path.unlink()
        logger.info(f"ReportSpecDocumentManager: restored {doc_id} from trash to {dest_folder}")
        return True

    def purge(self, doc_id: str) -> bool:
        """Permanently delete a document from trash/."""
        trash_path = self._paths["trash"] / f"{doc_id}.md"
        if not trash_path.exists():
            return False
        trash_path.unlink()
        return True

    def list_inbox(self) -> List[Dict[str, str]]:
        """Return list of inbox report specs, auto-parsing and registering them."""
        folder_path = self._paths["inbox"]
        entries = []
        for md in sorted(folder_path.glob("*.md"), reverse=True):
            content = md.read_text(encoding="utf-8", errors="replace")
            # Auto-register spec in-memory
            try:
                from advisor.report_spec_parser import parse_report_spec_markdown, register_report_spec
                spec = parse_report_spec_markdown(content)
                register_report_spec(md.stem, spec)
            except Exception as e:
                logger.error(f"Failed to auto-register report spec {md.name}: {e}")
                
            title = self._extract_title(content)
            status = self._extract_status(content)
            entries.append({
                "doc_id": md.stem,
                "title": title,
                "status": status,
                "folder": "inbox",
                "path": str(md),
            })
        return entries

    def list_outbox(self) -> List[Dict[str, str]]:
        """Return list of executed reports."""
        return self._list_folder("outbox")

    def list_trash(self) -> List[Dict[str, str]]:
        """Return list of trashed reports."""
        return self._list_folder("trash")

    def folder_of(self, doc_id: str) -> Optional[str]:
        """Return folder containing doc_id."""
        for folder in ("inbox", "outbox", "trash"):
            if (self._paths[folder] / f"{doc_id}.md").exists():
                return folder
        
        base_doc_id = re.sub(r'_executed_\d{8}_\d{6}$', '', doc_id)
        for folder in ("inbox", "outbox", "trash"):
            if (self._paths[folder] / f"{base_doc_id}.md").exists():
                return folder
            # Also check for any executed runs of this base_doc_id in the folder
            runs = list(self._paths[folder].glob(f"{base_doc_id}_executed_*.md"))
            if runs:
                return folder
        return None

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
