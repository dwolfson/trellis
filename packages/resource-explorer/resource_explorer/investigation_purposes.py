"""Investigation purposes: an Egeria valid-value list, seeded by RE, read back with a labelled cache.

**Decision (project owner, 2026-10-13):** "Egeria holds the set of record." Purposes
(`ProjectCharter.purposes`) are an Egeria valid-value list. RE keeps a local cache, labelled as a cache and
stale-aware, used only when Egeria cannot be read. The tuple that used to live in `registry.py`
(`VALID_PURPOSES`) is gone as the authority.

**Decision (project owner, 2026-10-13):** "warn only - suggestive everywhere". A purpose outside the list is
never rejected: it is kept, and a warning names it (`unknown_purpose_warnings`).

Three parts, one module:

* **The seed and its heal** (`ensure_purposes`), modelled on the data-class bootstrap
  (`surveyors/database/bootstrap_data_classes.py`): `configdata/investigation_purposes.yaml`; one canary
  `ValidValueDefinition::ResourceExplorer::InvestigationPurposeSeed::<fingerprint>` created last; the set and
  its values are plain `ValidValueDefinition`s (Egeria 6.2 rejects typeName `ValidValueSet`,
  OMAG-COMMON-400-018), bodies from the data-class bootstrap's own `_vvd_body`; membership is
  `ValidValueMember` carrying only `isDefaultValue` and `ordinal`. Leader-only (`still_leader()` before the
  first write), idempotent, and it only ADDS: nothing is updated or deleted.
* **The look-up rule** (PR #637): only pyegeria's exact miss sentence, or Egeria's typed not-found, is
  "absent"; anything else is could-not-check, and a pass that could not check creates nothing more.
* **The reader** (`current_purposes`): Egeria's set and its members, cached in `app_settings` with the time
  it was read. When Egeria cannot be read the cache answers, and the words say it is a cache and how old;
  with no cache, the shipped seed answers, and the words say that too.

**Dry run.** `ensure_purposes(..., dry_run=True)` walks the SAME code path with every create and link
recorded as "would create" instead of sent, so what is shown is what the write would do (project rule:
anything shown or counted comes from the same function as the write). By hand:
`python -m resource_explorer.investigation_purposes --dry-run`.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import json
import logging
import re
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resource_explorer.config import egeria_platform_url, egeria_view_server
from resource_explorer.egeria_absence import (
    ABSENT,
    guid_from_answer,
    is_absent,
    lookup_could_not_be_made,
)
from resource_explorer.surveyors.database.bootstrap_data_classes import (
    CouldNotCheck,
    _normalise,
    _related_guids,
    _sentence,
    _vvd_body,
)

log = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parent / "configdata" / "investigation_purposes.yaml"

VVD_TYPE = "ValidValueDefinition"
MEMBER_REL = "ValidValueMember"
SET_QN = "ValidValuesSet::InvestigationPurposes"
SET_DISPLAY_NAME = "Investigation purposes"
SET_DESCRIPTION = ("Why an investigation exists (ProjectCharter.purposes). Suggestive, not authoritative: a "
                   "purpose outside this list is kept and flagged. Seeded by Resource Explorer; extend it here.")
VALUE_PREFIX = "ValidValueDefinition::InvestigationPurpose::"
CANARY_PREFIX = "ValidValueDefinition::ResourceExplorer::InvestigationPurposeSeed::"

#: The `app_settings` key the reader's cache lives under (an existing key-value table: no DDL).
CACHE_KEY = "investigation_purposes.egeria_cache"
#: A cached copy older than this is labelled stale.
STALE_AFTER_SECONDS = 24 * 3600
#: How long one read (from Egeria, or a fallback) answers before the next request reads again.
MEMO_SECONDS = 300
MEMO_FAILURE_SECONDS = 60
#: A read from Egeria that has not answered by then falls back to the cache.
FETCH_TIMEOUT_SECONDS = 15

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
MAX_PURPOSES = 100


# ── the seed ──────────────────────────────────────────────────────────────────

class SeedError(ValueError):
    """The seed file is unreadable or an entry is invalid; the message names the file and entry."""


def _validate(raw: Any, source: str) -> dict:
    block = raw.get("investigation_purposes") if isinstance(raw, dict) else None
    if not isinstance(block, dict) or not isinstance(block.get("values"), list):
        raise SeedError(f"{source}: expected 'investigation_purposes' with a 'values' list")
    values, seen = [], set()
    for i, entry in enumerate(block["values"], start=1):
        where = f"{source}: value {i}"
        if not isinstance(entry, dict):
            raise SeedError(f"{where}: not a mapping")
        unknown = sorted(set(entry) - {"name", "description"})
        if unknown:
            raise SeedError(f"{where}: unknown field(s) {unknown}")
        name = entry.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise SeedError(f"{where}: 'name' must be letters and digits, starting with a letter")
        if name.lower() in seen:
            raise SeedError(f"{where}: purpose '{name}' appears twice")
        desc = entry.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise SeedError(f"{where} ({name}): 'description' must be a non-empty string")
        seen.add(name.lower())
        values.append({"name": name, "description": desc.strip()})
    if not values:
        raise SeedError(f"{source}: no purposes")
    if len(values) > MAX_PURPOSES:
        raise SeedError(f"{source}: {len(values)} purposes, more than {MAX_PURPOSES}")
    default = block.get("default", "")
    if default and default not in {v["name"] for v in values}:
        raise SeedError(f"{source}: default '{default}' is not one of the values")
    return {"default": default or "", "values": values}


def load_seed(path: str | Path | None = None) -> dict:
    """The validated seed: {"default": name, "values": [{"name", "description"}, ...]}."""
    import yaml

    p = Path(path) if path else SEED_FILE
    try:
        raw = yaml.safe_load(p.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise SeedError(f"{p}: unreadable ({exc})") from exc
    return _validate(raw, str(p))


def seed_fingerprint(seed: dict) -> str:
    return hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest()[:12]


def canary_qualified_name(seed: dict) -> str:
    return CANARY_PREFIX + seed_fingerprint(seed)


def value_qn(name: str) -> str:
    return VALUE_PREFIX + name


# ── look-ups (PR #637's rule) ─────────────────────────────────────────────────

def _lookup(client, qualified_name: str) -> str:
    """The element's GUID; "" ONLY when Egeria says it holds none (pyegeria's exact miss sentence, or a typed
    not-found); `CouldNotCheck` for anything else. Typed `ValidValueDefinition`, exact qualifiedName."""
    try:
        raw = client.get_guid_for_name(qualified_name, property_name=["qualifiedName"], type_name=VVD_TYPE)
    except Exception as exc:
        if is_absent(exc) == ABSENT:
            return ""
        raise CouldNotCheck(lookup_could_not_be_made(qualified_name, exc)) from exc
    return guid_from_answer(raw, qualified_name, CouldNotCheck)


# ── bodies ────────────────────────────────────────────────────────────────────

def _set_body() -> dict:
    return _vvd_body(SET_QN, SET_DISPLAY_NAME, description=SET_DESCRIPTION)


def _value_body(value: dict) -> dict:
    return _vvd_body(value_qn(value["name"]), value["name"], description=value["description"],
                     preferredValue=value["name"])


def _canary_body(canary: str) -> dict:
    return _vvd_body(canary, "RE investigation-purpose seed",
                     description="Present when Resource Explorer's investigation-purpose seed with this "
                                 "fingerprint ran to completion. Created by RE; do not edit.")


def _member_body(ordinal: int, is_default: bool) -> dict:
    # Egeria 6.2's ValidValueMemberProperties carries isDefaultValue and ordinal, nothing else (read live
    # 2026-10-13). An explicit body, never the no-body call (bootstrap_data_classes._member_body).
    return {
        "class": "NewRelationshipRequestBody",
        "properties": {"class": "ValidValueMemberProperties", "isDefaultValue": bool(is_default),
                       "ordinal": int(ordinal)},
    }


# ── the outcome ───────────────────────────────────────────────────────────────

PRESENT = "present"
CREATED = "created"
DRY_RUN = "dry run"
COULD_NOT_CHECK = "could not check"
FAILED = "failed"


@dataclass
class PurposeSeedOutcome:
    status: str
    values: int = 0
    created: list[dict] = field(default_factory=list)  # {"kind", "qualified_name", "guid" | "would_create" | "egeria_said"}
    reason: str = ""
    canary: str = ""

    @property
    def elements_created(self) -> list[dict]:
        return [c for c in self.created if c.get("guid") and c["kind"] not in ("canary", "link")]

    @property
    def links_made(self) -> list[dict]:
        return [c for c in self.created if c["kind"] == "link" and c.get("made")]

    @property
    def would_create(self) -> list[dict]:
        """A dry run's plan: every element (canary included) and link the write would make, in order."""
        return [c for c in self.created if c.get("would_create")]

    @property
    def line(self) -> str:
        if self.status == PRESENT:
            return f"investigation purposes: present, {self.values} values"
        if self.status == DRY_RUN:
            els = [c for c in self.would_create if c["kind"] != "link"]
            links = [c for c in self.would_create if c["kind"] == "link"]
            if not els and not links:
                return f"investigation purposes: dry run · nothing to create, {self.values} values present"
            return (f"investigation purposes: dry run · would create {len(els)} element"
                    f"{'' if len(els) == 1 else 's'} and {len(links)} link{'' if len(links) == 1 else 's'}")
        if self.status == CREATED:
            n, k = len(self.elements_created), len(self.links_made)
            what = [f"{n} element{'' if n == 1 else 's'} created"] if n else []
            what += [f"{k} link{'' if k == 1 else 's'} made"] if k else []
            return f"investigation purposes: created, {self.values} values ({', '.join(what) or 'nothing new'})"
        return f"investigation purposes: {self.status} · {self.reason}"

    def change_key(self) -> tuple:
        return (self.status, _normalise(self.reason),
                frozenset(c["guid"] for c in self.created if c.get("guid")))

    def as_dict(self) -> dict:
        return {"status": self.status, "values": self.values, "created": self.created,
                "reason": self.reason, "canary": self.canary, "line": self.line}


class _Stop(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


class _Writer:
    """Every create and link of a pass goes through here: sent, or (dry run) recorded as would-be. The
    leader check runs once, before the first real write."""

    def __init__(self, created: list[dict], dry_run: bool, still_leader):
        self.created, self.dry_run, self.still_leader = created, dry_run, still_leader
        self._checked = False

    def _before_write(self):
        if self.dry_run or self._checked:
            return
        if self.still_leader is not None and self.still_leader() is False:
            raise _Stop(COULD_NOT_CHECK, "this process no longer holds the bootstrap lock; nothing written")
        self._checked = True

    def create(self, fn, kind: str, qualified_name: str, body: dict) -> str:
        if self.dry_run:
            self.created.append({"kind": kind, "qualified_name": qualified_name, "would_create": True})
            return f"(new {qualified_name})"
        self._before_write()
        try:
            guid = guid_from_answer(fn(body), qualified_name, ValueError)
        except Exception as exc:
            self.created.append({"kind": kind, "qualified_name": qualified_name, "egeria_said": _sentence(exc)})
            raise _Stop(FAILED, f"creating '{qualified_name}': {_sentence(exc)}") from exc
        if not guid:
            self.created.append({"kind": kind, "qualified_name": qualified_name, "egeria_said": "no GUID returned"})
            raise _Stop(FAILED, f"creating '{qualified_name}': Egeria returned no GUID")
        self.created.append({"kind": kind, "qualified_name": qualified_name, "guid": guid})
        log.info("investigation purposes: created %s '%s' (%s)", kind, qualified_name, guid)
        return guid

    def link(self, fn, what: str, *args, **kwargs) -> None:
        if self.dry_run:
            self.created.append({"kind": "link", "qualified_name": what, "would_create": True})
            return
        self._before_write()
        try:
            fn(*args, **kwargs)
        except Exception as exc:
            self.created.append({"kind": "link", "qualified_name": what, "egeria_said": _sentence(exc)})
            raise _Stop(FAILED, f"linking {what}: {_sentence(exc)}") from exc
        self.created.append({"kind": "link", "qualified_name": what, "made": True})


def _heal(ref_manager, expert, seed: dict, canary: str, canary_present: bool, writer: _Writer) -> int:
    set_guid = _lookup(ref_manager, SET_QN)
    set_new = not set_guid
    if set_new:
        set_guid = writer.create(ref_manager.create_valid_value_definition, "purpose set", SET_QN, _set_body())
    # The set's member links are READ before any link is made, so a value whose link failed on an earlier
    # pass is linked now, never re-created. A new set has none.
    members = set() if set_new else _related_guids(expert, set_guid, MEMBER_REL)
    for ordinal, value in enumerate(seed["values"]):
        qn = value_qn(value["name"])
        guid = _lookup(ref_manager, qn)
        if not guid:
            guid = writer.create(ref_manager.create_valid_value_definition, "purpose", qn, _value_body(value))
        if guid not in members:
            writer.link(ref_manager.link_valid_value_definition, f"'{value['name']}' into {SET_QN}",
                        set_guid, guid, body=_member_body(ordinal, value["name"] == seed["default"]))
    # Last, and only when every element and link above is present: the canary.
    if not canary_present:
        writer.create(ref_manager.create_valid_value_definition, "canary", canary, _canary_body(canary))
    return len(seed["values"])


def ensure_purposes(ref_manager, expert=None, seed: dict | None = None, still_leader=None,
                    dry_run: bool = False) -> PurposeSeedOutcome:
    """The one code path, for the start-up heal, the manual run and the dry run. Never raises.

    Canary present: the set and each value are verified by typed look-up; all there is PRESENT, nothing is
    created. Canary absent (or something missing): the heal looks up each element, creates only what is
    missing, links what is unlinked (after reading the set's member links), and creates the canary last.
    """
    created: list[dict] = []
    canary = ""
    try:
        seed = seed if seed is not None else load_seed()
        canary = canary_qualified_name(seed)
        canary_present = bool(_lookup(ref_manager, canary))
        if canary_present:
            missing = [qn for qn in [SET_QN] + [value_qn(v["name"]) for v in seed["values"]]
                       if not _lookup(ref_manager, qn)]
            if not missing:
                return PurposeSeedOutcome(DRY_RUN if dry_run else PRESENT, values=len(seed["values"]),
                                          canary=canary)
            log.warning("investigation purposes: canary present but %d missing (%s) — healing",
                        len(missing), ", ".join(missing))
        if expert is None:
            raise CouldNotCheck("could not check the member links: no MetadataExpert client")
        n = _heal(ref_manager, expert, seed, canary, canary_present, _Writer(created, dry_run, still_leader))
        if dry_run:
            return PurposeSeedOutcome(DRY_RUN, values=n, created=created, canary=canary)
        outcome = PurposeSeedOutcome(CREATED, values=n, created=created, canary=canary)
        if not outcome.elements_created and not outcome.links_made:
            outcome.status = PRESENT
        return outcome
    except CouldNotCheck as exc:
        status = FAILED if any(c.get("guid") for c in created) else COULD_NOT_CHECK
        return PurposeSeedOutcome(status, created=created, reason=str(exc), canary=canary)
    except _Stop as stop:
        return PurposeSeedOutcome(stop.status, created=created, reason=stop.reason, canary=canary)
    except SeedError as exc:
        return PurposeSeedOutcome(FAILED, reason=f"the seed file: {exc}", canary=canary)
    except Exception as exc:  # noqa: BLE001 - a start-up heal never raises
        status = FAILED if any(c.get("guid") for c in created) else COULD_NOT_CHECK
        return PurposeSeedOutcome(status, created=created, reason=_sentence(exc), canary=canary)


# ── reading the list back from Egeria ─────────────────────────────────────────

class PurposesUnavailable(RuntimeError):
    """Egeria's list could not be read (or holds no set yet); the message says why."""


def _props(element: dict) -> dict:
    props = element.get("elementProperties") or {}
    strings = props.get("propertiesAsStrings")
    if isinstance(strings, dict):
        return strings
    pvm = props.get("propertyValueMap") or {}
    return {k: (v or {}).get("primitiveValue") for k, v in pvm.items() if isinstance(v, dict)}


def read_purposes_from_egeria(ref_manager, expert) -> list[dict]:
    """[{"name", "description", "is_default", "ordinal"}] — the members of Egeria's purposes set, in its
    order. Raises `PurposesUnavailable` when the set is absent, the look-up fails, or the set is empty."""
    try:
        set_guid = _lookup(ref_manager, SET_QN)
    except CouldNotCheck as exc:
        raise PurposesUnavailable(str(exc)) from exc
    if not set_guid:
        raise PurposesUnavailable(f"Egeria holds no '{SET_QN}' yet (RE's start-up heal creates it)")
    try:
        raw = expert.get_related_metadata_elements(set_guid, MEMBER_REL, body={"class": "ResultsRequestBody"})
    except Exception as exc:
        raise PurposesUnavailable(f"could not read the members of '{SET_QN}': {_sentence(exc)}") from exc
    if isinstance(raw, str) and is_absent(raw) == ABSENT:
        raise PurposesUnavailable(f"'{SET_QN}' has no values in Egeria")
    items = raw.get("elementList") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise PurposesUnavailable(f"could not read the members of '{SET_QN}': unreadable answer {str(raw)[:80]!r}")
    out = []
    for it in items:
        # Members only: from the set, a member is the element at end 2 (live-read 2026-10-13).
        if not isinstance(it, dict) or it.get("elementAtEnd1") is not False:
            continue
        el = it.get("element") or {}
        p = _props(el)
        name = str(p.get("preferredValue") or p.get("displayName") or "").strip()
        if not name:
            continue
        rel = ((it.get("relationshipProperties") or {}).get("propertiesAsStrings") or {})
        try:
            ordinal = int(rel.get("ordinal", 0))
        except (TypeError, ValueError):
            ordinal = 0
        out.append({"name": name, "description": str(p.get("description") or ""),
                    "is_default": str(rel.get("isDefaultValue", "")).lower() == "true", "ordinal": ordinal})
    if not out:
        raise PurposesUnavailable(f"'{SET_QN}' has no values in Egeria")
    out.sort(key=lambda v: (v["ordinal"], v["name"].lower()))
    return out


# ── the reader: Egeria, else the labelled cache, else the shipped seed ────────

SOURCE_EGERIA = "egeria"
SOURCE_CACHE = "cache"
SOURCE_SEED = "seed"


@dataclass
class PurposeList:
    values: list[dict]
    source: str              # egeria | cache | seed
    as_of: str = ""          # when the list was read from Egeria ("" for the seed)
    stale: bool = False
    words: str = ""          # what the screen says about where the list came from
    reason: str = ""         # why Egeria was not read (cache / seed only)

    @property
    def names(self) -> list[str]:
        return [v["name"] for v in self.values]

    @property
    def default(self) -> str:
        return next((v["name"] for v in self.values if v.get("is_default")), "")

    def as_dict(self) -> dict:
        return {"purposes": self.names, "values": self.values, "source": self.source, "as_of": self.as_of,
                "stale": self.stale, "words": self.words, "reason": self.reason, "default": self.default}


def _age_words(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 90:
        return "just now"
    if s < 90 * 60:
        return f"{round(s / 60)} minutes ago"
    if s < 36 * 3600:
        return f"{round(s / 3600)} hours ago"
    return f"{round(s / 86400)} days ago"


def _seed_list(reason: str) -> PurposeList:
    try:
        seed = load_seed()
    except SeedError as exc:  # pragma: no cover - the shipped seed is validated by its own test
        log.error("investigation purposes: %s", exc)
        seed = {"default": "", "values": []}
    values = [{"name": v["name"], "description": v["description"], "is_default": v["name"] == seed["default"],
               "ordinal": i} for i, v in enumerate(seed["values"])]
    return PurposeList(values, SOURCE_SEED, words=(
        "RE's shipped list, not Egeria's: Egeria's list could not be read and RE holds no cached copy"
        + (f" ({reason})" if reason else "")), reason=reason)


def write_cache(registry, values: list[dict], read_at: str | None = None) -> str:
    read_at = read_at or datetime.now(UTC).isoformat()
    registry.set_setting(CACHE_KEY, json.dumps({"values": values, "read_at": read_at}))
    return read_at


def read_cache(registry) -> dict | None:
    try:
        raw = registry.get_setting(CACHE_KEY)
        data = json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001 - an unreadable cache is no cache, said in the words
        log.warning("investigation purposes: cache unreadable: %s", exc)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("values"), list) or not data["values"]:
        return None
    return data


def _cache_list(cache: dict, reason: str, now: float) -> PurposeList:
    read_at = str(cache.get("read_at") or "")
    try:
        age = now - datetime.fromisoformat(read_at).timestamp()
    except ValueError:
        age = float("inf")
    stale = age > STALE_AFTER_SECONDS
    when = _age_words(age) if age != float("inf") else "at an unknown time"
    words = (f"cached copy · read from Egeria {when}{' · stale' if stale else ''} · Egeria could not be read now"
             + (f" ({reason})" if reason else ""))
    return PurposeList(cache["values"], SOURCE_CACHE, as_of=read_at, stale=stale, words=words, reason=reason)


_memo: tuple[float, float, PurposeList] | None = None      # (stamped at, ttl, answer)
_memo_lock = threading.Lock()
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="purposes-read")


def _registry(registry):
    if registry is not None:
        return registry
    from resource_explorer.registry import ProjectRegistry

    return ProjectRegistry()


def reset_memo() -> None:
    global _memo
    with _memo_lock:
        _memo = None


def current_purposes(registry=None, fetch: Callable[[], list[dict]] | None = None, *,
                     timeout: float = FETCH_TIMEOUT_SECONDS, use_memo: bool = True) -> PurposeList:
    """The purposes list for a screen or a check. Never raises.

    `fetch()` reads Egeria (`read_purposes_from_egeria` with some identity's clients); on success the cache
    is rewritten and the list is Egeria's. With no `fetch`, or when it fails or times out: the cache, labelled
    with its age (stale after a day); with no cache, the shipped seed, labelled as not Egeria's.
    """
    global _memo
    now = time.time()
    if use_memo:
        with _memo_lock:
            if _memo and now - _memo[0] < _memo[1]:
                return _memo[2]
    reason = "" if fetch else "not read from Egeria here"
    answer: PurposeList | None = None
    if fetch is not None:
        ctx = contextvars.copy_context()
        future = _pool.submit(ctx.run, fetch)
        try:
            values = future.result(timeout=timeout)
            read_at = datetime.now(UTC).isoformat()
            try:
                write_cache(_registry(registry), values, read_at)
            except Exception as exc:  # noqa: BLE001 - the list is still Egeria's; the cache just did not move
                log.warning("investigation purposes: could not write the cache: %s", exc)
            answer = PurposeList(values, SOURCE_EGERIA, as_of=read_at, words="Egeria's list · read just now")
        except concurrent.futures.TimeoutError:
            reason = f"Egeria did not answer in {int(timeout)}s"
        except Exception as exc:  # noqa: BLE001 - every failure falls back, with its words
            reason = _sentence(exc)
    if answer is None:
        try:
            cache = read_cache(_registry(registry))
        except Exception as exc:  # noqa: BLE001
            cache, reason = None, reason or _sentence(exc)
        answer = _cache_list(cache, reason, now) if cache else _seed_list(reason)
    if use_memo:
        with _memo_lock:
            _memo = (now, MEMO_SECONDS if answer.source == SOURCE_EGERIA else MEMO_FAILURE_SECONDS, answer)
    return answer


def known_purpose_names(registry=None) -> list[str]:
    """The names a check compares against WITHOUT calling Egeria: the cache, else the shipped seed."""
    try:
        return current_purposes(registry, fetch=None, use_memo=False).names
    except Exception:  # noqa: BLE001 - a check never fails on its vocabulary
        return _seed_list("").names


def _fold(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def is_listed(value: str, names: list[str]) -> bool:
    return _fold(value) in {_fold(n) for n in names}


def unknown_purpose_warnings(values: list[str], names: list[str], where: str = "") -> list[str]:
    """One sentence per value outside the list, naming it. Suggestive, so these warn and never reject."""
    out = []
    for v in values:
        if v and not is_listed(v, names):
            out.append(f"{where}purpose '{v}' is not in the investigation-purposes list; kept as written")
    return out


# ── Egeria clients ────────────────────────────────────────────────────────────

def _clients(identity, purpose: str):
    from pyegeria.omvs.metadata_expert import MetadataExpert
    from pyegeria.omvs.reference_data import ReferenceDataManager

    from resource_explorer.egeria_clients import egeria_client

    clients = egeria_client(identity, purpose=purpose, view_server=egeria_view_server(),
                            platform_url=egeria_platform_url())
    return clients.of(ReferenceDataManager), clients.of(MetadataExpert)


def fetch_as_caller() -> list[dict]:
    """Read Egeria's list as the signed-in person (the purposes route). Raises without one."""
    from resource_explorer.egeria_clients import Caller

    if not egeria_platform_url():
        raise PurposesUnavailable("Egeria is not configured")
    ref_manager, expert = _clients(Caller(), "read investigation purposes")
    return read_purposes_from_egeria(ref_manager, expert)


# ── proof ─────────────────────────────────────────────────────────────────────

def record_outcome(outcome: PurposeSeedOutcome, registry=None) -> str:
    """One activity row for the pass: summary = the outcome line, items = every element created (GUID) or
    refused (Egeria's sentence). Best effort; returns the row id or ""."""
    try:
        from resource_explorer.registry import ActivityEntry

        registry = _registry(registry)
        entry_id = str(uuid.uuid4())
        registry.write_activity(ActivityEntry(
            id=entry_id, ts=datetime.now(UTC).isoformat(), operation="bootstrap",
            intent="curate", entity_type="egeria", entity_slug="investigation-purposes",
            entity_name="Investigation purposes", entity_location=outcome.canary,
            status="ok" if outcome.status in (PRESENT, CREATED) else "error",
            summary=outcome.line, detail=json.dumps(outcome.as_dict()), items=outcome.created,
        ))
        return entry_id
    except Exception as exc:  # noqa: BLE001
        log.warning("investigation purposes: could not record the outcome: %s", exc)
        return ""


# ── the monitor's pass ────────────────────────────────────────────────────────

_last_key: tuple | None = None
_last_outcome: PurposeSeedOutcome | None = None
_state_lock = threading.Lock()


def _still_bootstrap_leader() -> bool | None:
    from resource_explorer.leader_election import LOCK_BOOTSTRAP, still_leader

    return still_leader(LOCK_BOOTSTRAP)


def check_and_heal_purposes(registry=None) -> PurposeSeedOutcome:
    """One monitor pass as the daemon (`DaemonReason.BOOTSTRAP`), after the data-class seed. Heals, then (on
    present/created) refreshes the reader's cache from Egeria. Logs and records an activity row only when the
    outcome changes. Never raises."""
    global _last_key, _last_outcome
    from resource_explorer.egeria_clients import Daemon, DaemonReason

    ref_manager = expert = None
    if not egeria_platform_url():
        outcome = PurposeSeedOutcome(COULD_NOT_CHECK, reason="Egeria not configured")
    else:
        try:
            ref_manager, expert = _clients(Daemon(DaemonReason.BOOTSTRAP), "bootstrap investigation purposes")
        except Exception as exc:  # noqa: BLE001
            outcome = PurposeSeedOutcome(COULD_NOT_CHECK, reason=_sentence(exc))
        else:
            outcome = ensure_purposes(ref_manager, expert, still_leader=_still_bootstrap_leader)
    if outcome.status in (PRESENT, CREATED) and ref_manager is not None:
        try:
            write_cache(_registry(registry), read_purposes_from_egeria(ref_manager, expert))
            reset_memo()
        except Exception as exc:  # noqa: BLE001 - the cache keeps its last copy, labelled with its age
            log.warning("investigation purposes: cache not refreshed: %s", exc)
    key = outcome.change_key()
    with _state_lock:
        changed = key != _last_key
        _last_key, _last_outcome = key, outcome
    if changed:
        (log.info if outcome.status in (PRESENT, CREATED) else log.warning)(outcome.line)
        record_outcome(outcome, registry)
    return outcome


def status() -> dict:
    with _state_lock:
        return _last_outcome.as_dict() if _last_outcome else {"status": "not checked yet", "line": ""}


# ── by hand ───────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """`python -m resource_explorer.investigation_purposes [--dry-run]`. The dry run reads only, writes
    nothing to Egeria and records nothing: it prints each element and link the heal would create."""
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    if not egeria_platform_url():
        log.error("EGERIA_PLATFORM_URL is not set. Cannot connect to Egeria.")
        return 1
    from resource_explorer.egeria_clients import Daemon, DaemonReason

    ref_manager, expert = _clients(Daemon(DaemonReason.BOOTSTRAP), "bootstrap investigation purposes")
    outcome = ensure_purposes(ref_manager, expert, dry_run=dry_run)
    print(outcome.line)
    for c in outcome.created:
        print(f"  {c['kind']:12s} {c['qualified_name']}"
              + ("  (would create)" if c.get("would_create") else f"  {c.get('guid') or c.get('egeria_said', '')}"))
    if not dry_run:
        record_outcome(outcome)
    return 0 if outcome.status in (PRESENT, CREATED, DRY_RUN) else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    sys.exit(main())
