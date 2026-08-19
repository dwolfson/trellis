"""Detect and repair wiped Dr.Egeria-authored definitions.

In a development environment the Egeria database is reset regularly, which
silently deletes everything RE's Survey tab depends on: the shared glossaries
and perspectives, the Question terms, and the Survey Definitions themselves.
Nothing in RE noticed — the Survey tab just quietly degraded (empty candidate
lists, or a ~20s full instance scan on every load in place of a ~0.2s scoped
lookup) with no error surfaced anywhere. This module closes that gap by
checking, at web startup and periodically thereafter, whether each batch of
Dr.Egeria command documents is still present in Egeria, and re-executing the
ones that are not.

Patterned on egeria-workspaces' PyegeriaWebHandler bootstrap (bootstrap_monitor_
handler.py / bootstrap_batches.py), adapted where RE's content differs — see
"Where this diverges" below.

## Model

`docs/dr-egeria/` is organised as *batches*: one directory per ordered
execution group, each containing a `_batch.json` manifest plus its command
documents. A top-level `_folder_order.json` gives the cross-batch order.
Only directories with a `_batch.json` are batches, so root-level files (the CSV
sources of truth, one-off probe/debug documents) are never executed.

Each batch declares a *canary*: one element whose presence in Egeria means that
batch ran to completion. Presence is the entire detection mechanism — there is
no staleness detection, deliberately. Re-running a batch is how it gets fixed,
and re-running an already-present batch is the one thing we must never do (see
IDEMPOTENCY), so "is it there?" is the only question worth asking.

## Ordering is load-bearing, not cosmetic

Batches run in `_folder_order.json` order because the content is genuinely
dependent: Question terms are created inside glossaries that foundations.md
defines, and each Survey Definition's "Link Element To Scope" commands bind it
to Question terms *by name*. Process the survey-definitions batch while the
questions batch is absent and every command still reports success, but no
ScopedBy link is created — leaving a Survey Definition that looks perfectly
healthy (its own canary is present) while the scoped lookup depending on those
links silently returns nothing. That is precisely the state RE was found in on
2026-08-19.

## IDEMPOTENCY — why heals are gated on missing-only

Dr.Egeria's `Create X` commands are name-keyed upserts and safe to re-run, but
its `Link First/Next Process Step` commands are NOT: re-running a document
against an already-linked process creates a *second* edge per step rather than
merging. SurveyDefinitionReader then sees two outgoing next-steps, correctly
refuses to guess which chain was meant, and the whole Survey Definition drops
out of service. Confirmed live twice (2026-08-13, and again 2026-08-19 when
re-running all four documents produced 22 duplicate edges at once).

So: a batch is healed ONLY when its canary is missing. A present batch is never
re-run "just in case". Batches that are inherently unsafe to re-run additionally
declare `"idempotent": false`, and may declare a `post_heal` script — for the
survey definitions that is the reconciler, which strips duplicate edges a heal
may itself have introduced.

## Failure behaviour

Fails *open* on connection errors: if Egeria is unreachable the canary check
returns "present", because an unreachable server is not evidence of a reset and
healing on that basis would re-run everything against a server that is merely
briefly down. Startup is never blocked — the initial check runs inside the
scheduler thread, and any exception is logged and swallowed.

A canary that can never resolve would otherwise re-heal its batch on every
single pass, forever; `_consecutive_failures` caps repeated attempts per batch
so a mis-specified canary degrades to "logged and left alone" rather than an
infinite heal loop hammering Egeria. This is not hypothetical: two Question
terms in scouting-questions.md do not resolve after a successful run (both
contain apostrophes), which is exactly how such a canary gets chosen by mistake.

## Where this diverges from the Portal's version

- Canary matching accepts `qualified_name` OR `display_name`, and `type` is
  optional. The Portal keys on (type, displayName). RE needs both forms because
  its two canary populations behave oppositely: Perspective qualified names are
  author-controlled and stable, while Dr.Egeria *generates* glossary-term
  qualified names with a deployment-specific org prefix and version
  ("Coco Pharmaceuticals::Term::...::1.0") that must not be hard-coded.
- `_folder_order.json` may be either a bare JSON array (the Portal's shape) or
  an object with a "folders" key (RE's, so the file can carry comments). Both
  parse, so a Portal-style file works here unchanged.
- Adds `idempotent` and `post_heal`, which the Portal has no equivalent of.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria"
FOLDER_ORDER_FILE = "_folder_order.json"
BATCH_MANIFEST_FILE = "_batch.json"

# How long between periodic checks. The startup check alone would miss the
# common dev case where only the Egeria container is reset while the RE web
# process keeps running, hence a loop rather than a one-shot.
CHECK_INTERVAL_SECONDS = 600

# Per-document timeout for `dr_egeria --process`. scouting-questions.md is ~52KB
# and creates 41 terms, so this is generous by design.
HEAL_TIMEOUT_SECONDS = 900

# After this many consecutive failed heals, stop retrying a batch until the
# process restarts or a manual run is requested. Guards the infinite-heal-loop
# failure mode described in the module docstring.
MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class Batch:
    """One folder of Dr.Egeria command documents plus its manifest."""

    batch_id: str
    path: Path
    display_name: str
    canary: dict
    files: list[str]
    idempotent: bool = True
    post_heal: dict | None = None

    @property
    def has_canary(self) -> bool:
        """A batch with no usable canary is never auto-healed — there is no way
        to tell whether it needs it, and guessing means risking a re-run."""
        c = self.canary or {}
        return bool(c.get("qualified_name") or c.get("display_name"))


@dataclass
class BatchStatus:
    present: bool | None = None          # None = not yet checked
    last_checked_at: str = ""
    last_healed_at: str = ""
    last_heal_result: str = ""
    consecutive_failures: int = 0


_status: dict[str, BatchStatus] = {}
_status_lock = threading.Lock()
_reinitializing = False
_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── discovery ───────────────────────────────────────────────────────────────

def _read_folder_order(docs_dir: Path) -> list[str]:
    """Parse _folder_order.json, tolerating both the bare-array shape the
    Portal uses and RE's object form (which exists so the file can carry
    explanatory comments — JSON arrays cannot)."""
    f = docs_dir / FOLDER_ORDER_FILE
    if not f.is_file():
        return []
    try:
        raw = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("bootstrap: unreadable %s (%s) — falling back to alphabetical", f, exc)
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, dict):
        return [str(x) for x in raw.get("folders", [])]
    log.warning("bootstrap: %s is neither array nor object — ignoring", f)
    return []


def discover_batches(docs_dir: Path = DOCS_DIR) -> list[Batch]:
    """Find every batch folder and return them in execution order.

    Ordering follows _folder_order.json; any batch on disk not named there runs
    afterwards, alphabetically (matching the Portal's rule — never skipped,
    never silently first). A name in the order file matching nothing on disk is
    ignored rather than raising, so deleting a folder doesn't break startup.
    """
    if not docs_dir.is_dir():
        return []

    found: dict[str, Batch] = {}
    for child in sorted(docs_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / BATCH_MANIFEST_FILE
        if not manifest_path.is_file():
            # Not a batch. Deliberate: dropping a folder into docs/dr-egeria/
            # must not silently make it execute against Egeria.
            continue
        try:
            raw = json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("bootstrap: skipping %s — unreadable manifest (%s)", child.name, exc)
            continue

        declared = [str(x) for x in raw.get("files", [])]
        on_disk = sorted(p.name for p in child.glob("*.md"))
        # Declared order first (dropping any that no longer exist), then
        # everything else alphabetically — same rule as folder ordering.
        files = [f for f in declared if (child / f).is_file()]
        files += [f for f in on_disk if f not in files]

        found[child.name] = Batch(
            batch_id=child.name,
            path=child,
            display_name=raw.get("display_name") or raw.get("displayName") or child.name,
            canary=raw.get("canary") or {},
            files=files,
            idempotent=bool(raw.get("idempotent", True)),
            post_heal=raw.get("post_heal"),
        )

    ordered_names = _read_folder_order(docs_dir)
    ordered = [found[n] for n in ordered_names if n in found]
    ordered += [b for name, b in sorted(found.items()) if name not in ordered_names]
    return ordered


# ── canary check ────────────────────────────────────────────────────────────

def canary_present(batch: Batch, client=None) -> bool:
    """Is this batch's canary element in Egeria?

    Returns True (i.e. "no heal needed") on any lookup error — see the module
    docstring on failing open. An unreachable Egeria is not evidence of a reset,
    and treating it as one would re-run every batch against a server that is
    merely restarting.
    """
    if not batch.has_canary:
        return True

    if client is None:
        try:
            from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

            client = SurveyDefinitionReader()._connect_classification_explorer()
        except Exception as exc:
            log.debug("bootstrap: cannot reach Egeria for %s (%s) — assuming present", batch.batch_id, exc)
            return True

    from resource_explorer.surveyors.survey_definition_reader import _as_guid

    c = batch.canary
    if c.get("qualified_name"):
        prop, name = "qualifiedName", c["qualified_name"]
    else:
        prop, name = "displayName", c["display_name"]

    kwargs = {"property_name": [prop]}
    # type is optional on purpose: a wrong type_name silently returns nothing,
    # which reads as "missing" and triggers a heal. Matching on the globally
    # unique qualified_name alone is safer than guessing a type.
    if c.get("type"):
        kwargs["type_name"] = c["type"]

    try:
        return _as_guid(client.get_guid_for_name(name, **kwargs)) is not None
    except Exception as exc:
        log.debug("bootstrap: canary lookup failed for %s (%s) — assuming present", batch.batch_id, exc)
        return True


# ── heal ────────────────────────────────────────────────────────────────────

def _run_dr_egeria(doc: Path) -> tuple[bool, str]:
    """Execute one document. Runs `dr_egeria` as a subprocess from the
    document's own directory, matching how these documents are run by hand and
    keeping relative paths resolving the same way."""
    try:
        proc = subprocess.run(
            ["dr_egeria", "--process", "--summary-only", doc.name],
            cwd=str(doc.parent),
            capture_output=True,
            text=True,
            timeout=HEAL_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return False, "dr_egeria CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {HEAL_TIMEOUT_SECONDS}s"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"{type(exc).__name__}: {exc}"

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, f"exit {proc.returncode}: {tail[-1] if tail else 'no output'}"
    return True, "ok"


def _run_post_heal(batch: Batch) -> tuple[bool, str]:
    """Run a batch's post-heal repair script, if it declares one.

    Exists for the survey-definitions batch: a legitimate heal still duplicates
    step links, because Dr.Egeria's Link First/Next Process Step commands do not
    dedupe. Without this the batch would come back from a heal already broken.
    """
    spec = batch.post_heal or {}
    script = spec.get("script")
    if not script:
        return True, ""

    pkg_root = Path(__file__).resolve().parent.parent
    script_path = pkg_root / script
    if not script_path.is_file():
        return False, f"post_heal script not found: {script}"

    import sys

    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(pkg_root),
            capture_output=True,
            text=True,
            timeout=HEAL_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return False, f"post_heal {type(exc).__name__}: {exc}"

    if proc.returncode != 0:
        return False, f"post_heal exit {proc.returncode}"
    return True, "post_heal ok"


def heal_batch(batch: Batch) -> tuple[bool, str]:
    """Re-execute every document in a batch, in order, then its post-heal step.

    Stops at the first failing document: within a batch, file order encodes
    dependency order, so continuing past a failure would run commands whose
    prerequisites are missing — the same class of silent-partial-success this
    whole module exists to prevent.
    """
    for filename in batch.files:
        ok, detail = _run_dr_egeria(batch.path / filename)
        if not ok:
            return False, f"{filename}: {detail}"

    ok, detail = _run_post_heal(batch)
    if not ok:
        return False, detail
    return True, detail or "ok"


# ── orchestration ───────────────────────────────────────────────────────────

def check_and_heal(docs_dir: Path = DOCS_DIR, force: bool = False) -> dict:
    """Check every batch and heal the missing ones, in declared order.

    force=True re-runs every batch regardless of canary state. It exists for the
    admin "run everything" action and is deliberately NOT the default: for a
    batch with idempotent=false a forced re-run duplicates relationships and
    takes the Survey Definition out of service, so callers must opt in
    explicitly and surface a confirmation to the user.
    """
    global _reinitializing

    batches = discover_batches(docs_dir)
    results: dict[str, dict] = {}
    _reinitializing = True
    try:
        for batch in batches:
            with _status_lock:
                st = _status.setdefault(batch.batch_id, BatchStatus())

            if st.consecutive_failures >= MAX_CONSECUTIVE_FAILURES and not force:
                results[batch.batch_id] = {"action": "skipped", "reason": "too many consecutive failures"}
                continue

            present = False if force else canary_present(batch)
            with _status_lock:
                st.present = present if not force else st.present
                st.last_checked_at = _now()

            if present:
                results[batch.batch_id] = {"action": "ok", "reason": "canary present"}
                continue

            log.info("bootstrap: %s missing — healing (%d file(s))", batch.batch_id, len(batch.files))
            ok, detail = heal_batch(batch)
            with _status_lock:
                st.last_healed_at = _now()
                st.last_heal_result = "ok" if ok else detail
                st.consecutive_failures = 0 if ok else st.consecutive_failures + 1
                # Re-check rather than assuming the heal worked: a canary that
                # never resolves is exactly how an infinite heal loop starts.
                st.present = canary_present(batch) if ok else False
            results[batch.batch_id] = {"action": "healed" if ok else "failed", "reason": detail}
    finally:
        _reinitializing = False

    return {"batches": results}


def get_status(docs_dir: Path = DOCS_DIR) -> dict:
    """Status for the admin banner / status endpoint."""
    out = {}
    for batch in discover_batches(docs_dir):
        with _status_lock:
            st = _status.get(batch.batch_id, BatchStatus())
        out[batch.batch_id] = {
            "display_name": batch.display_name,
            "present": st.present,
            "last_checked_at": st.last_checked_at,
            "last_healed_at": st.last_healed_at,
            "last_heal_result": st.last_heal_result,
            "consecutive_failures": st.consecutive_failures,
            "idempotent": batch.idempotent,
            "file_count": len(batch.files),
        }
    return {"reinitializing": _reinitializing, "batches": out}


# ── scheduler ───────────────────────────────────────────────────────────────

def _loop(docs_dir: Path, interval: int, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            check_and_heal(docs_dir)
        except Exception:
            # Never let a bad pass kill the loop — the next tick should still
            # get a chance to notice and repair a reset.
            log.exception("bootstrap: check pass failed")
        stop.wait(interval)


def start_scheduler(docs_dir: Path = DOCS_DIR, interval: int = CHECK_INTERVAL_SECONDS) -> None:
    """Start the background check loop. Never blocks or fails startup.

    A daemon thread rather than an asyncio task, matching scheduler.py's
    existing precedent for request-independent background work in this codebase,
    and because the heal itself is blocking subprocess work.
    """
    global _stop_event, _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event = threading.Event()
    _thread = threading.Thread(
        target=_loop,
        args=(docs_dir, interval, _stop_event),
        daemon=True,
        name="resource-explorer-bootstrap",
    )
    _thread.start()
    log.info("bootstrap: monitor started (every %ss)", interval)


def stop_scheduler() -> None:
    global _stop_event, _thread
    if _stop_event is not None:
        _stop_event.set()
    _thread = None
