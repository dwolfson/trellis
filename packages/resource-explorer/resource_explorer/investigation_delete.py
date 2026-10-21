"""Delete an investigation (owner ruling 2026-10-21): permanent, with an Egeria choice asked each time.

Two choices for an investigation that was promoted to an Egeria Project:

* ``re_only``         "Delete in Resource Explorer only": the local investigation and everything that exists only for
                      it go; the Egeria Project, its working-set Collection and its journal Notes stay in Egeria.
* ``re_and_egeria``   "Delete in Resource Explorer and Egeria": the Egeria elements RE made for it go first, then the
                      local ones.

An investigation that was never promoted has only the first choice.

Who: its owner (``investigations.created_by``) or a Portal admin or curator (``workflows.curate.CURATOR_ROLES``, the
role the rest of RE already honours as "may curate anything"). Nobody else; an ownerless investigation is an admin's.

The Egeria side runs as the signed-in person (``Caller()``), never a daemon, in the order the live check of
2026-10-21 proved (``~/.re-gate/scripts/journal_publish_check_cleanup.py``), ONE element per call, never a cascade:

    1. read the NoteLogs attached to the Project and each log's Notes (reads only; a failed read stops here);
    2. ``remove_note`` per Note, then ``remove_note_log`` per log;
    3. ``delete_collection`` per Collection the investigation's working sets recorded (the Folio, disposition sets);
    4. ``delete_project``.

Only what the investigation created is touched. A member's own asset (repo, database, file system) is never read,
unlinked or deleted here. The Project is deleted only when RE made it (its qualifiedName is the one ``promote``
writes); a Project that was already in Egeria when the investigation was bound to it is left, and said so. A
NoteLog RE did not make (not ``NoteLog::RE::<project guid>``) and a Collection whose qualifiedName is not RE's are
left and said so.

Each deleted GUID is re-read with ``MetadataExpert.get_metadata_element_by_guid``. Gone means Egeria answered
"No element found" (a string); an exception or a populated answer is "could not tell" / "still there", never gone.

If any Egeria delete is refused or cannot be confirmed, everything stops: nothing is retried, the local investigation
is kept, and the result names what was deleted and what remains, with Egeria's words. Pressing Delete again resumes
(an element already gone is skipped).

The local side is ``ProjectRegistry.delete_investigation_local`` (one transaction, which also writes the activity row).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

log = logging.getLogger(__name__)

CHOICE_RE_ONLY = "re_only"
CHOICE_RE_AND_EGERIA = "re_and_egeria"
CHOICES = (CHOICE_RE_ONLY, CHOICE_RE_AND_EGERIA)

#: Placeholder words (the WORDS table for the designer lives in the front end; these are the server's).
WORDS = {
    "sign_in": "Sign in to delete an investigation.",
    "not_yours": "Only the person who created this investigation, or a Portal admin or curator, can delete it.",
    "ownerless": "This investigation has no recorded owner, so only a Portal admin or curator can delete it.",
    "not_promoted": "This investigation was never promoted to Egeria, so there is nothing in Egeria to delete.",
    "publish_running": "A publish for this investigation is running now. Try again in a minute.",
    "project_not_ours": ("left in Egeria: this Project was already in Egeria when the investigation was linked to it, "
                         "so Resource Explorer did not create it"),
    "note_log_not_ours": "left in Egeria: this NoteLog was not made by Resource Explorer",
    "collection_not_ours": "left in Egeria: this Collection was not made by Resource Explorer for this investigation",
    "already_gone": "already gone from Egeria",
}


def project_qualified_name(slug: str) -> str:
    """The qualifiedName ``EgeriaInvestigationPublisher.promote`` gives a Project it creates."""
    return f"Project::Investigation::{slug}"


def delete_rights(inv: dict, identity) -> tuple[bool, str]:
    """May this caller delete this investigation? ``(allowed, words)``; words are "" when allowed.

    ``identity`` is ``a2a_auth.caller()``: owner = the signed-in user whose id equals ``created_by``; admin = a
    signed-in user whose Portal role is in ``CURATOR_ROLES`` (the same override ``curation_access`` rule 2 uses)."""
    from resource_explorer.workflows.curate import CURATOR_ROLES

    if identity is None or getattr(identity, "auth_source", "") == "anonymous" or not getattr(identity, "user_id", ""):
        return False, WORDS["sign_in"]
    if (getattr(identity, "role", "") or "").lower() in CURATOR_ROLES:
        return True, ""
    owner = (inv.get("created_by") or "").strip()
    if owner and owner == identity.user_id:
        return True, ""
    return False, WORDS["not_yours"] if owner else WORDS["ownerless"]


@dataclass
class DeleteResult:
    slug: str
    choice: str
    #: True only when the local investigation was removed.
    local_deleted: bool = False
    #: True when the Egeria side was asked for and completed (always False for ``re_only``).
    egeria_done: bool = False
    #: Egeria elements removed and confirmed gone: ``{kind, guid, name}``.
    deleted: list[dict] = field(default_factory=list)
    #: Egeria elements this delete meant to remove and did not: ``{kind, guid, name, why}``.
    remaining: list[dict] = field(default_factory=list)
    #: Egeria elements deliberately not touched: ``{kind, guid, name, why}``.
    left: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    local_counts: dict = field(default_factory=dict)
    activity_id: str = ""

    @property
    def ok(self) -> bool:
        return self.local_deleted and not self.remaining and not self.errors

    def as_dict(self) -> dict:
        return {"slug": self.slug, "choice": self.choice, "ok": self.ok, "local_deleted": self.local_deleted,
                "egeria_done": self.egeria_done, "deleted": self.deleted, "remaining": self.remaining,
                "left": self.left, "errors": self.errors, "local_counts": self.local_counts,
                "activity_id": self.activity_id}


class _Stop(Exception):
    """Stop the Egeria side: the words say why."""


@dataclass
class EgeriaHandles:
    pm: object   # ProjectManager
    cm: object   # CollectionManager
    me: object   # MetadataExpert


def caller_handles() -> EgeriaHandles:
    """The three pyegeria clients, as the signed-in person (``Caller()``); never the daemon."""
    from pyegeria import CollectionManager, MetadataExpert, ProjectManager

    from resource_explorer.egeria_clients import Caller, egeria_client

    clients = egeria_client(Caller(), purpose="investigation delete")
    return EgeriaHandles(pm=clients.of(ProjectManager), cm=clients.of(CollectionManager),
                         me=clients.of(MetadataExpert))


def _words_of(exc: BaseException) -> str:
    """Egeria's own words for a failure: the security refusal sentence, else the exception as pyegeria raised it."""
    try:
        from resource_explorer.egeria_outbox import _refusal_sentence, is_security_refusal

        if isinstance(exc, Exception) and is_security_refusal(exc):
            return f"refused by Egeria: {_refusal_sentence(exc)}"
    except Exception:  # noqa: BLE001 - the words must still come out
        pass
    return f"{type(exc).__name__}: {' '.join(str(exc).split())[:400]}"


def _guid(el) -> str:
    if not isinstance(el, dict):
        return ""
    return str((el.get("elementHeader") or {}).get("guid") or el.get("guid") or "")


def _props(el) -> dict:
    p = el.get("properties") if isinstance(el, dict) else None
    return p if isinstance(p, dict) else {}


def _name(el) -> str:
    p = _props(el)
    return str(p.get("displayName") or p.get("qualifiedName") or "")


def _elements(answer, what: str) -> list[dict]:
    """The elements of a pyegeria list answer. "No elements found" (a string) is an honest empty; any other
    answer (None, other text, a wrong shape) is "could not read", which stops the delete rather than meaning none."""
    from resource_explorer.egeria_absence import ABSENT, is_absent

    if isinstance(answer, list):
        return [e for e in answer if isinstance(e, dict) and _guid(e)]
    if isinstance(answer, str) and is_absent(answer) == ABSENT:
        return []
    raise _Stop(f"could not read {what} from Egeria (it answered {str(answer)[:200]!r}), so nothing was deleted there")


class InvestigationDeleter:
    """One delete. Build with the registry and the caller's rights already checked; ``run`` does the rest."""

    def __init__(self, registry, *, handles_factory: "Callable[[], EgeriaHandles] | None" = None,
                 sleep: "Callable[[float], None] | None" = None, confirm_tries: int = 3):
        self._registry = registry
        # Looked up at call time (not bound as a default) so a test can replace the module's `caller_handles`.
        self._handles_factory = handles_factory or (lambda: caller_handles())
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))
        self._tries = confirm_tries

    # ── Egeria helpers ──────────────────────────────────────────────────────────────────────────────────

    def _read_back(self, me, guid: str, tries: "int | None" = None) -> "bool | None":
        """True: Egeria says no such element. False: still readable. None: could not tell (an exception, or an
        answer that is neither). Retried a few times: a delete can take a moment to show."""
        from resource_explorer.egeria_absence import ABSENT, is_absent

        verdict: "bool | None" = None
        tries = self._tries if tries is None else tries
        for attempt in range(tries):
            try:
                found = me.get_metadata_element_by_guid(guid)
            except Exception as exc:  # noqa: BLE001 - an exception is "could not tell", never "gone"
                log.info("read-back of %s raised %s", guid, type(exc).__name__)
                verdict = None
            else:
                if isinstance(found, str):
                    verdict = True if is_absent(found) == ABSENT else None
                elif isinstance(found, (dict, list)) and found:
                    verdict = False
                else:
                    verdict = None
            if verdict is True:
                return True
            if attempt + 1 < tries:
                self._sleep(1.0)
        return verdict

    def _remove(self, res: DeleteResult, me, kind: str, guid: str, name: str, call: Callable[[str], object]) -> None:
        """Delete ONE element, then confirm it by GUID. Raises ``_Stop`` (after recording it) on a refusal or when
        it cannot be confirmed gone."""
        before = self._read_back(me, guid, tries=1)
        if before is True:
            res.deleted.append({"kind": kind, "guid": guid, "name": name, "note": WORDS["already_gone"]})
            return
        try:
            call(guid)
        except Exception as exc:  # noqa: BLE001
            why = _words_of(exc)
            res.remaining.append({"kind": kind, "guid": guid, "name": name, "why": why})
            raise _Stop(f"Egeria would not delete the {kind} {name or guid}: {why}") from exc
        after = self._read_back(me, guid)
        if after is True:
            res.deleted.append({"kind": kind, "guid": guid, "name": name})
            return
        why = ("the delete was sent but Egeria still returns it" if after is False
               else "the delete was sent but Egeria could not be asked whether it is gone")
        res.remaining.append({"kind": kind, "guid": guid, "name": name, "why": why})
        raise _Stop(f"could not confirm the {kind} {name or guid} is gone: {why}")

    # ── the Egeria side ─────────────────────────────────────────────────────────────────────────────────

    def _plan_and_run_egeria(self, res: DeleteResult, inv: dict) -> None:
        slug = inv["slug"]
        project_guid = (inv.get("egeria_project_guid") or "").strip()
        h = self._handles_factory()
        pm, cm, me = h.pm, h.cm, h.me
        project_ours = (inv.get("egeria_project_qualified_name") or "").strip() == project_qualified_name(slug)

        # 1. reads only, all of them before the first delete.
        notes_by_log: dict[str, list[dict]] = {}
        logs: list[dict] = []
        project_gone = self._read_back(me, project_guid, tries=1) is True
        if not project_gone:
            from resource_explorer.feedback_egeria import note_log_qualified_name

            ours_qn = note_log_qualified_name(project_guid)
            for lg in _elements(pm.get_attached_note_logs(project_guid), "the Project's NoteLogs"):
                if _props(lg).get("qualifiedName") == ours_qn:
                    logs.append(lg)
                else:
                    res.left.append({"kind": "NoteLog", "guid": _guid(lg), "name": _name(lg),
                                     "why": WORDS["note_log_not_ours"]})
            for lg in logs:
                notes_by_log[_guid(lg)] = _elements(pm.get_notes_for_note_log(_guid(lg)),
                                                    f"the Notes in NoteLog {_name(lg) or _guid(lg)}")

        collections = self._registry.investigation_egeria_collections(slug)

        # 2. Notes, then NoteLogs.
        for lg in logs:
            for n in notes_by_log[_guid(lg)]:
                self._remove(res, me, "Note", _guid(n), _name(n), pm.remove_note)
        for lg in logs:
            self._remove(res, me, "NoteLog", _guid(lg), _name(lg), pm.remove_note_log)

        # 3. Collections the investigation's working sets recorded (only if RE's own qualifiedName).
        prefixes = (f"Folio::Investigation::{slug}", f"WorkingSet::Investigation::{slug}::")
        for c in collections:
            guid = c["guid"]
            qn = self._collection_qualified_name(cm, guid)
            if qn is None:
                if self._read_back(me, guid, tries=1) is True:
                    res.deleted.append({"kind": "Collection", "guid": guid, "name": c["working_set_slug"],
                                        "note": WORDS["already_gone"]})
                    continue
                res.remaining.append({"kind": "Collection", "guid": guid, "name": c["working_set_slug"],
                                      "why": "could not read it to check that Resource Explorer made it"})
                raise _Stop(f"could not read the Collection {guid} to check that Resource Explorer made it, "
                            "so it was not deleted")
            if not qn.startswith(prefixes):
                res.left.append({"kind": "Collection", "guid": guid, "name": qn, "why": WORDS["collection_not_ours"]})
                continue
            self._remove(res, me, "Collection", guid, qn, cm.delete_collection)

        # 4. the Project, only when RE made it.
        if not project_ours:
            res.left.append({"kind": "Project", "guid": project_guid,
                             "name": inv.get("egeria_project_qualified_name") or "", "why": WORDS["project_not_ours"]})
        elif not project_gone:
            self._remove(res, me, "Project", project_guid, project_qualified_name(slug), pm.delete_project)
        else:
            res.deleted.append({"kind": "Project", "guid": project_guid, "name": project_qualified_name(slug),
                                "note": WORDS["already_gone"]})

    def _collection_qualified_name(self, cm, guid: str) -> "str | None":
        """The qualifiedName of a recorded Collection, read as the caller; None when it could not be read (or is
        gone: the caller then asks Egeria by GUID which of the two it was)."""
        try:
            got = cm.get_collection_by_guid(guid, graph_query_depth=0)
        except Exception as exc:  # noqa: BLE001
            log.info("could not read Collection %s: %s", guid, type(exc).__name__)
            return None
        if isinstance(got, dict):
            qn = _props(got).get("qualifiedName")
            return str(qn) if qn else None
        return None

    # ── the whole delete ────────────────────────────────────────────────────────────────────────────────

    def run(self, slug: str, choice: str, *, by: str, role: str = "") -> DeleteResult:
        """Delete the investigation. Raises ``ValueError`` for a choice that cannot apply (unknown, or Egeria on an
        investigation with no Project) and ``LookupError`` when it is not there; everything else is in the result."""
        if choice not in CHOICES:
            raise ValueError(f"unknown choice {choice!r}; valid: {list(CHOICES)}")
        # Read as a service reader: rights were decided by the caller (it needs the row even for an admin who
        # could not otherwise see a private one); the row's existence is not in question here.
        inv = self._registry.get_investigation(slug, user_id="")
        if not inv:
            raise LookupError(slug)
        project_guid = (inv.get("egeria_project_guid") or "").strip()
        if choice == CHOICE_RE_AND_EGERIA and not project_guid:
            raise ValueError(WORDS["not_promoted"])
        res = DeleteResult(slug=slug, choice=choice)

        if choice == CHOICE_RE_AND_EGERIA:
            try:
                self._plan_and_run_egeria(res, inv)
                res.egeria_done = True
            except _Stop as stop:
                res.errors.append(str(stop))
            except Exception as exc:  # noqa: BLE001 - clients could not be built, a read raised, ...
                res.errors.append(f"the Egeria side stopped: {_words_of(exc)}")
            if res.errors:
                # Local investigation kept. The activity row says what happened; the screen gets the same.
                self._write_activity(res, inv, by=by, role=role, deleted_locally=False)
                return res

        counts_activity = self._activity(res, inv, by=by, role=role, deleted_locally=True)
        res.activity_id = counts_activity.id
        res.local_counts = self._registry.delete_investigation_local(slug, counts_activity)
        res.local_deleted = True
        return res

    # ── the activity row ────────────────────────────────────────────────────────────────────────────────

    def _activity(self, res: DeleteResult, inv: dict, *, by: str, role: str, deleted_locally: bool):
        import json

        from resource_explorer.registry import ActivityEntry

        choice_words = ("Resource Explorer only" if res.choice == CHOICE_RE_ONLY
                        else "Resource Explorer and Egeria")
        guid = (inv.get("egeria_project_guid") or "").strip()
        if res.choice == CHOICE_RE_ONLY:
            behind = ([{"kind": "Project", "guid": guid, "name": inv.get("egeria_project_qualified_name") or ""}]
                      + [{"kind": "Collection", "guid": c["guid"], "name": c["working_set_slug"]}
                         for c in self._registry.investigation_egeria_collections(inv["slug"])]) if guid else []
        else:
            behind = [dict(r) for r in res.remaining] + [dict(r) for r in res.left]
        if deleted_locally:
            summary = (f"deleted '{inv.get('display_name') or inv['slug']}' in {choice_words}"
                       f" · by {by or 'unknown'}"
                       + (f" · {len(res.deleted)} Egeria element(s) removed" if res.choice == CHOICE_RE_AND_EGERIA
                          else "")
                       + (f" · {len(behind)} left in Egeria" if behind else ""))
            status = "ok"
        else:
            summary = (f"delete of '{inv.get('display_name') or inv['slug']}' stopped in Egeria · by {by or 'unknown'}"
                       f" · {len(res.deleted)} removed, {len(res.remaining)} remain; the investigation was kept")
            status = "error"
        detail = {"event": "investigation_delete", "choice": res.choice, "by": by, "role": role,
                  "deleted_locally": deleted_locally, "egeria_project_guid": guid,
                  "egeria_deleted": res.deleted, "egeria_remaining": res.remaining, "egeria_left": res.left,
                  "left_behind_in_egeria": behind, "errors": res.errors}
        return ActivityEntry(
            id=str(uuid.uuid4()), ts=datetime.now(UTC).isoformat(), operation="delete", intent="enrichment",
            entity_type="investigation", entity_slug=inv["slug"], entity_name=inv.get("display_name") or "",
            status=status, summary=summary, detail=json.dumps(detail),
            items=[{"kind": d["kind"], "guid": d["guid"], "state": "deleted"} for d in res.deleted]
            + [{"kind": d["kind"], "guid": d["guid"], "state": "left" if d in res.left or res.choice == CHOICE_RE_ONLY
                else "remains"} for d in behind])

    def _write_activity(self, res: DeleteResult, inv: dict, *, by: str, role: str, deleted_locally: bool) -> None:
        try:
            entry = self._activity(res, inv, by=by, role=role, deleted_locally=deleted_locally)
            self._registry.write_activity(entry)
            res.activity_id = entry.id
        except Exception:  # noqa: BLE001 - the stop is the safety property; the row is its record
            log.exception("could not record the stopped delete of %s", inv.get("slug"))
