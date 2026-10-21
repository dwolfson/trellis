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
    3. per Collection the investigation's working sets recorded (the Folio, disposition sets): ``remove_from_collection``
       for each member (the CollectionMembership only; the member's own asset is never touched), then
       ``delete_collection`` (Egeria refuses a Collection that still has members);
    4. read everything still anchored to the Project (``get_anchored_element_graph``); if any of it is not on RE's own
       list above, STOP before the Project step and name it (type, GUID, name, author);
    5. ``_retire_project`` (today ``delete_project``; the one place to swap if the design session rules for archive).

Only what the investigation created is touched. A member's own asset (repo, database, file system) is never read,
unlinked or deleted here. The Project is deleted only when RE made it (its qualifiedName is the one ``promote``
writes); a Project that was already in Egeria when the investigation was bound to it is left, and said so. A
NoteLog RE did not make (not ``NoteLog::RE::<project guid>``) and a Collection whose qualifiedName is not exactly the
one RE gave that working set are left and said so, unless the Project step would remove them (anchored to it): then
they are named as what stops the Project, never as "left alone".

Each deleted GUID is re-read with ``MetadataExpert.get_metadata_element_by_guid`` and classified with
``egeria_absence``: gone means Egeria answered "No element found" (a string) or raised a not-found
(``is_absent == ABSENT``), or, for a GUID this run has just deleted, raised 400-010 "not visible" (soft-deleted). A
401/403, an unavailable server, a timeout or a populated answer is "could not tell" / "still there", never gone.

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
    "anchored_blocks": ("anchored to the Project, and Resource Explorer is not removing it, so the Project step would "
                        "delete it too"),
    "project_blocked": "not deleted: elements anchored to it that Resource Explorer is not removing",
    "local_failed": ("Egeria's side finished, but removing the investigation from Resource Explorer failed, so it "
                     "is still here. Pressing Delete again skips what is already gone from Egeria"),
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
    #: Collection memberships removed (the member's own element is untouched): ``{kind, guid, name, collection}``.
    unlinked: list[dict] = field(default_factory=list)
    #: Egeria elements deliberately not touched: ``{kind, guid, name, why}``.
    left: list[dict] = field(default_factory=list)
    #: Elements anchored to the Project that RE is not removing, so the Project step did not run:
    #: ``{kind, guid, name, author, why}``.
    blocking: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    local_counts: dict = field(default_factory=dict)
    activity_id: str = ""

    @property
    def ok(self) -> bool:
        return self.local_deleted and not self.remaining and not self.errors

    def as_dict(self) -> dict:
        return {"slug": self.slug, "choice": self.choice, "ok": self.ok, "local_deleted": self.local_deleted,
                "egeria_done": self.egeria_done, "deleted": self.deleted, "unlinked": self.unlinked,
                "remaining": self.remaining, "left": self.left, "blocking": self.blocking, "errors": self.errors, "local_counts": self.local_counts,
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


def collection_qualified_name(slug: str, record: dict) -> str:
    """The qualifiedName ``EgeriaInvestigationPublisher`` gave the Collection of one working set: the Folio's, or the
    disposition set's. Compared by equality; a record that fits neither has no expected name (so nothing matches)."""
    if record.get("collection_kind") == "folio":
        return f"Folio::Investigation::{slug}"
    disposition = (record.get("disposition") or "").strip()
    return f"WorkingSet::Investigation::{slug}::{disposition}" if disposition else ""


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


def _type_name(el) -> str:
    h = el.get("elementHeader") if isinstance(el, dict) else None
    t = (h or {}).get("type") if isinstance(h, dict) else None
    return str((t or {}).get("typeName") or "") if isinstance(t, dict) else ""


def _display(el) -> str:
    """A name for an anchored element: its displayName or qualifiedName, else (a Comment, a Rating) a clip of its text."""
    p = _props(el)
    name = p.get("displayName") or p.get("qualifiedName")
    if name:
        return str(name)
    text = p.get("commentText") or p.get("review") or p.get("description") or ""
    return " ".join(str(text).split())[:80]


def _author(el) -> str:
    """Who created it, when Egeria says (``versions.createdBy`` on the header or the element); '' otherwise."""
    if not isinstance(el, dict):
        return ""
    h = el.get("elementHeader") if isinstance(el.get("elementHeader"), dict) else {}
    for versions in ((h or {}).get("versions"), el.get("versions")):
        if isinstance(versions, dict) and versions.get("createdBy"):
            return str(versions["createdBy"])
    return ""


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

    def _read_back(self, me, guid: str, tries: "int | None" = None, *, just_deleted: bool = False) -> "bool | None":
        """True: gone. False: still readable. None: could not tell. Classified with ``egeria_absence``:

        * gone: Egeria's "No element found" answer, or a raised not-found (``is_absent == ABSENT``; live Egeria
          raises ``PyegeriaNotFoundException`` for a deleted GUID), or, only when ``just_deleted`` (this run sent
          the delete), a 400-010 "not visible" (the soft-deleted shape);
        * still there: a populated answer;
        * could not tell: 401/403, an unavailable server, a timeout, any other exception or answer.

        Retried a few times: a delete can take a moment to show."""
        from resource_explorer.egeria_absence import ABSENT, is_absent, is_not_visible

        verdict: "bool | None" = None
        tries = self._tries if tries is None else tries
        for attempt in range(tries):
            try:
                found = me.get_metadata_element_by_guid(guid)
            except Exception as exc:  # noqa: BLE001 - classified below; only a typed not-found is "gone"
                log.info("read-back of %s raised %s", guid, type(exc).__name__)
                if is_absent(exc) == ABSENT or (just_deleted and is_not_visible(exc)):
                    verdict = True
                else:
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
        it cannot be confirmed gone. An element already gone (same classification as the confirm, minus the
        "not visible" shape that only a delete sent by this run explains) is skipped: nothing is re-sent."""
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
        after = self._read_back(me, guid, just_deleted=True)
        if after is True:
            res.deleted.append({"kind": kind, "guid": guid, "name": name})
            return
        why = ("the delete was sent but Egeria still returns it" if after is False
               else "the delete was sent but Egeria could not be asked whether it is gone")
        res.remaining.append({"kind": kind, "guid": guid, "name": name, "why": why})
        raise _Stop(f"could not confirm the {kind} {name or guid} is gone: {why}")

    def _unlink_members(self, res: DeleteResult, cm, collection_guid: str, collection_name: str) -> None:
        """Take every member out of a Collection before it is deleted: Egeria refuses to delete a Collection that
        still has members (``validateNoCollectionMembers``). One ``remove_from_collection`` per member, which
        removes the CollectionMembership only; the member (a repo, a database, a file system: an asset that is not
        RE's to delete) is never deleted or changed, and ``cascade`` is never used. The membership list is re-read
        after each pass (a long list is paged), and a pass that unlinks nothing new stops the delete."""
        seen: set[str] = set()
        for _ in range(50):
            members = _elements(cm.get_collection_members(collection_guid), f"the members of {collection_name}")
            todo = [m for m in members if _guid(m) not in seen]
            if not members:
                return
            if not todo:
                names = ", ".join(_guid(m) for m in members[:5])
                res.remaining.append({"kind": "Collection", "guid": collection_guid, "name": collection_name,
                                      "why": f"members were unlinked but Egeria still lists: {names}"})
                raise _Stop(f"the Collection {collection_name} still lists members after they were unlinked "
                            f"({names}), so it was not deleted")
            for m in todo:
                mg = _guid(m)
                try:
                    cm.remove_from_collection(collection_guid, mg)
                except Exception as exc:  # noqa: BLE001
                    why = _words_of(exc)
                    res.remaining.append({"kind": "CollectionMembership", "guid": mg, "name": _name(m) or mg,
                                          "collection": collection_guid, "why": why})
                    raise _Stop(f"Egeria would not unlink {_name(m) or mg} from the Collection "
                                f"{collection_name}: {why}") from exc
                seen.add(mg)
                res.unlinked.append({"kind": "CollectionMembership", "guid": mg, "name": _name(m) or mg,
                                     "collection": collection_guid})
        raise _Stop(f"the Collection {collection_name} still has members after 50 passes, so it was not deleted")

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

        # 3. Collections the investigation's working sets recorded (only if RE's own qualifiedName, by equality).
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
            if qn != collection_qualified_name(slug, c):
                res.left.append({"kind": "Collection", "guid": guid, "name": qn, "why": WORDS["collection_not_ours"]})
                continue
            self._unlink_members(res, cm, guid, qn)
            self._remove(res, me, "Collection", guid, qn, cm.delete_collection)

        # 4. the Project, only when RE made it, and only when nothing is anchored to it that RE is not removing.
        if not project_ours:
            res.left.append({"kind": "Project", "guid": project_guid,
                             "name": inv.get("egeria_project_qualified_name") or "", "why": WORDS["project_not_ours"]})
        elif not project_gone:
            self._stop_if_anchored_elements_remain(res, me, project_guid)
            self._retire_project(res, me, pm, project_guid, project_qualified_name(slug))
        else:
            res.deleted.append({"kind": "Project", "guid": project_guid, "name": project_qualified_name(slug),
                                "note": WORDS["already_gone"]})

    def _stop_if_anchored_elements_remain(self, res: DeleteResult, me, project_guid: str) -> None:
        """Read everything anchored to the Project (``MetadataExpert.get_anchored_element_graph``): NoteLogs, Notes,
        Ratings, Comments, Likes and anything else Egeria anchors there. By now RE has removed what it made; every
        anchored element that is not one of those would be deleted WITH the Project, so if there is any, STOP before
        the Project step: keep the investigation, and name each element (type, GUID, name, author). The Project is
        listed as not deleted. Anything reported as "left" that is in this set is moved here: it is not left alone,
        it is what stops the Project."""
        graph = me.get_anchored_element_graph(project_guid)
        if isinstance(graph, dict) and isinstance(graph.get("element"), dict) and "anchoredElements" not in graph:
            graph = graph["element"]
        if not isinstance(graph, dict):
            raise _Stop(f"could not read what is anchored to the Project (Egeria answered {str(graph)[:200]!r}), "
                        "so the Project was not deleted")
        mine = {d["guid"] for d in res.deleted} | {project_guid}
        blocking = []
        for el in graph.get("anchoredElements") or []:
            g = _guid(el)
            if not g or g in mine:
                continue
            blocking.append({"kind": _type_name(el) or "element", "guid": g, "name": _display(el),
                             "author": _author(el), "why": WORDS["anchored_blocks"]})
        if not blocking:
            return
        res.blocking = blocking
        blocked = {b["guid"] for b in blocking}
        res.left = [x for x in res.left if x["guid"] not in blocked]
        res.remaining.append({"kind": "Project", "guid": project_guid, "name": "", "why": WORDS["project_blocked"]})
        named = "; ".join(f"{b['kind']} {b['guid']}" + (f" ({b['name']})" if b["name"] else "")
                          + (f" by {b['author']}" if b["author"] else "") for b in blocking)
        raise _Stop(f"the Project was not deleted: {len(blocking)} element(s) anchored to it are not ones Resource "
                    f"Explorer made, and deleting the Project would delete them too: {named}")

    def _retire_project(self, res: DeleteResult, me, pm, project_guid: str, name: str) -> None:
        """The final Project action: today ``delete_project``. The design session has yet to rule whether this should
        archive instead; this is the one place to swap, and the anchor check before it does not change."""
        self._remove(res, me, "Project", project_guid, name, pm.delete_project)

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

        # The very first step, in one transaction: refuse (InvestigationPublishRunning, the route's 409) if a drain
        # is writing one of this investigation's publish rows, else cancel the ones still waiting so none starts
        # while this runs. Nothing has been changed anywhere when it refuses.
        self._registry.begin_investigation_delete(slug)

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
        try:
            res.local_counts = self._registry.delete_investigation_local(slug, counts_activity)
        except Exception as exc:  # noqa: BLE001 - includes a drain that claimed a row since the first step
            # Egeria may be fully deleted by now. The local transaction rolled back, so the investigation is still
            # here; say so in words, and record in its OWN transaction what Egeria lost (the row that went with
            # the failed transaction is gone).
            log.exception("local delete of %s failed", slug)
            res.errors.append(f"{WORDS['local_failed'] if res.egeria_done else 'The investigation was not deleted'}"
                              f": {_words_of(exc)}")
            self._write_activity(res, inv, by=by, role=role, deleted_locally=False)
            return res
        res.activity_id = counts_activity.id
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
            behind = [dict(r) for r in res.remaining] + [dict(r) for r in res.left] + [dict(r) for r in res.blocking]
        if deleted_locally:
            summary = (f"deleted '{inv.get('display_name') or inv['slug']}' in {choice_words}"
                       f" · by {by or 'unknown'}"
                       + (f" · {len(res.deleted)} Egeria element(s) removed" if res.choice == CHOICE_RE_AND_EGERIA
                          else "")
                       + (f" · {len(behind)} left in Egeria" if behind else ""))
            status = "ok"
        else:
            where = ("in Resource Explorer after Egeria's side finished" if res.egeria_done
                     else "in Resource Explorer" if res.choice == CHOICE_RE_ONLY else "in Egeria")
            summary = (f"delete of '{inv.get('display_name') or inv['slug']}' stopped {where} · by {by or 'unknown'}"
                       f" · {len(res.deleted)} removed from Egeria, {len(res.remaining)} remain; "
                       "the investigation was kept")
            status = "error"
        detail = {"event": "investigation_delete", "choice": res.choice, "by": by, "role": role,
                  "deleted_locally": deleted_locally, "egeria_project_guid": guid,
                  "egeria_deleted": res.deleted, "egeria_unlinked": res.unlinked,
                  "egeria_remaining": res.remaining, "egeria_left": res.left, "egeria_blocking": res.blocking,
                  "left_behind_in_egeria": behind, "errors": res.errors}
        return ActivityEntry(
            id=str(uuid.uuid4()), ts=datetime.now(UTC).isoformat(), operation="delete", intent="enrichment",
            entity_type="investigation", entity_slug=inv["slug"], entity_name=inv.get("display_name") or "",
            status=status, summary=summary, detail=json.dumps(detail),
            items=[{"kind": d["kind"], "guid": d["guid"], "state": "deleted"} for d in res.deleted]
            + [{"kind": d["kind"], "guid": d["guid"], "state": "unlinked"} for d in res.unlinked]
            + [{"kind": d["kind"], "guid": d["guid"],
                "state": ("left" if d in res.left or res.choice == CHOICE_RE_ONLY
                          else "blocks the Project" if d in res.blocking else "remains")} for d in behind])

    def _write_activity(self, res: DeleteResult, inv: dict, *, by: str, role: str, deleted_locally: bool) -> None:
        try:
            entry = self._activity(res, inv, by=by, role=role, deleted_locally=deleted_locally)
            self._registry.write_activity(entry)
            res.activity_id = entry.id
        except Exception:  # noqa: BLE001 - the stop is the safety property; the row is its record
            log.exception("could not record the stopped delete of %s", inv.get("slug"))
