"""The persisted start entry of a coordinated run started with a one-run credential (review fix round 2, F2).

The in-memory start-pending mark (`run_credential_holder.starting`) dies with the process. A start that asked Egeria and
then lost its process (a restart between `initiate_process_run` and the run row's marker) would leave a run whose
steps nothing marks as "asked for a one-run credential", and those steps would be given the stored login. Owner, Q2:
after a restart the remaining steps are refused, never a fallback; over-refusal is the only acceptable failure mode.

So the start writes this entry BEFORE asking Egeria, through the existing `app_settings` table (`set_setting`; no DDL):

    key   run_credential_start::<slug>::<definition qualified name>
    value [{nonce, at, holder: {pid, started}, instance}, ...]      (JSON; nothing secret)

* written before `initiate_process_run`: if it cannot be written the run is not started (Egeria is never asked);
* after the holder entry and the run row's marker are written, the start removes its own entry (a removal that fails
  leaves it until the TTL: over-refusal at worst);
* when the marker could not be written, the entry is kept and names the instance Egeria returned, so it stands in for
  the marker;
* an entry older than the TTL (`run_credential_holder.configured_ttl`) is ignored and pruned on the next write.

The engine host reads it (`live_starts`) for an `re-*` step of that definition on that resource that has no holder entry
and no marker (`engine_host._one_run_credential`, `EngineHost._screen`).

Known limit: the value is read, changed and written back. Two PROCESSES starting the same definition on the same
resource in the same instant could each write over the other's entry; a lock serialises this within one process.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

KEY_PREFIX = "run_credential_start::"
#: How long a start of THIS process may stay between writing its entry and recording its marker before a step it could
#: own is refused rather than left for the next sweep: the initiate call's own timeout (pyegeria's 30 s read, 10 s
#: connect) plus the row write, with room to spare.
START_DEFER_SECONDS = 90.0

_LOCK = threading.Lock()


def start_key(slug: str, definition: str) -> str:
    return f"{KEY_PREFIX}{(slug or '').strip()}::{(definition or '').strip()}"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_when(text) -> datetime | None:
    """A naive-UTC datetime from the registry's ISO spelling (an aware one is converted); None when unreadable."""
    try:
        when = datetime.fromisoformat(str(text or "").strip())
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    return when


def _read(registry, key: str) -> list[dict]:
    raw = registry.get_setting(key)
    if not raw:
        return []
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError(f"start entry {key!r} is not a list")
    return [e for e in value if isinstance(e, dict)]


def _age_seconds(entry: dict, now: datetime) -> float | None:
    when = parse_when(entry.get("at"))
    return None if when is None else (now - when).total_seconds()


def _live(entries: list[dict], now: datetime) -> list[dict]:
    """Entries younger than the TTL. One whose time cannot be read is kept: unknown is never "stale"."""
    from resource_explorer.run_credential_holder import configured_ttl

    ttl = configured_ttl()
    out = []
    for e in entries:
        age = _age_seconds(e, now)
        if age is None or age < ttl:
            out.append(e)
    return out


def write_start(registry, slug: str, definition: str) -> str:
    """Write this start's entry (instance not yet known) and return its nonce. Raises when it cannot be written: the
    caller then does not start the run."""
    from resource_explorer.run_credential_holder import process_identity

    key = start_key(slug, definition)
    nonce = uuid.uuid4().hex
    with _LOCK:
        now = _now()
        entries = _live(_read(registry, key), now)
        entries.append({"nonce": nonce, "at": now.isoformat(), "holder": process_identity(), "instance": ""})
        registry.set_setting(key, json.dumps(entries))
    return nonce


def _rewrite(registry, slug: str, definition: str, nonce: str, change) -> None:
    key = start_key(slug, definition)
    with _LOCK:
        entries = _live(_read(registry, key), _now())
        registry.set_setting(key, json.dumps([x for x in (change(e) if e.get("nonce") == nonce else e
                                                          for e in entries) if x is not None]))


def name_instance(registry, slug: str, definition: str, nonce: str, instance: str) -> None:
    """Name the instance Egeria returned on this start's entry: the entry then stands in for a marker that could not be
    written. Raises when it cannot be written."""
    _rewrite(registry, slug, definition, nonce, lambda e: {**e, "instance": instance})


def remove_start(registry, slug: str, definition: str, nonce: str) -> None:
    """Remove this start's entry. Raises when it cannot be written (the caller logs it; the TTL ends it)."""
    _rewrite(registry, slug, definition, nonce, lambda e: None)


def live_starts(registry, slug: str, definition: str) -> list[dict]:
    """The entries for this definition on this resource younger than the TTL, each with its `age` in seconds (None when
    its time is unreadable). Raises when they cannot be read: the caller refuses, never guesses."""
    now = _now()
    return [{**e, "age": _age_seconds(e, now)} for e in _live(_read(registry, start_key(slug, definition)), now)]
