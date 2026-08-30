"""A SHA-keyed cache for the two things a survey downloads.

**The measurement that shaped this** (2026-08-30, `odpi/egeria-python`):

```
zipball download           23.74s   49.1 MB      <- the cost
zipball extract             0.39s                <- not the cost
treeless clone (network)     1.6s    1.7 MB      <- the cost
clone --local from a copy    0.28s               <- not the cost
default-branch SHA lookup    0.49s               <- the price of correctness
```

So this caches the **artifact**, never the working directory: the `.zip` and the
treeless clone. Every run still extracts, or `clone --local`s, into its own fresh
temporary directory.

That is deliberate and is the whole reason this is safe. `zipball_root()` and
`git_clone_root()` promise a caller a private directory it can do what it likes
with, and handing out a shared one would let two concurrent surveys — five
sessions run in this repo at once — see each other's mutations. A git directory
is worse than most: `git log` writes to `.git` for its own bookkeeping, so a
shared clone is a corruption risk, not merely a leak. Caching one layer further
back keeps the isolation and still removes 98% of the cost.

**Keyed on the commit SHA, which is what makes a stale hit impossible.** A cache
keyed on the repo alone would serve yesterday's code silently — the failure this
codebase keeps re-learning, and the one worth paying 0.49s per run to rule out.
When the SHA moves, the key misses and the old entry ages out.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

#: Total cache budget, evicted least-recently-used first. A zipball is tens of
#: megabytes and a treeless clone is single-digit, so this holds roughly the
#: whole 60-repo corpus at one SHA each. `data/repos/` is already ~1 GB for
#: eight checkouts, so this is not the biggest thing on disk by a distance.
DEFAULT_MAX_BYTES = 4 * 1024 * 1024 * 1024

#: Where entries live. Under `data/` beside the registry databases, so a
#: checkout stays self-contained and `rm -rf data/source-cache` is a complete,
#: safe reset.
DEFAULT_CACHE_DIR = Path("data/source-cache")


def _safe_key(full_name: str, sha: str) -> str:
    """`owner/repo` + sha -> one filesystem-safe path segment."""
    return f"{full_name.replace('/', '__')}__{sha[:12]}"


class SourceCache:
    """Artifacts keyed by (repo, commit SHA). Concurrency-safe by construction:
    every write lands in a sibling temporary path and is moved into place with
    `os.replace`/`Path.rename`, which is atomic on a single filesystem. Two
    sessions racing the same key both do the work and one wins the rename; the
    loser discards its copy. That wastes a download and can never serve a torn
    entry, which is the right way round.
    """

    def __init__(self, cache_dir: Path | str | None = None,
                 max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.root = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.max_bytes = max_bytes
        self.hits = 0
        self.misses = 0

    # ── lookup ────────────────────────────────────────────────────────────
    def _entry(self, kind: str, full_name: str, sha: str) -> Path:
        return self.root / kind / _safe_key(full_name, sha)

    def get(self, kind: str, full_name: str, sha: str) -> Path | None:
        """The cached artifact, or None. Touches it so eviction sees the use."""
        path = self._entry(kind, full_name, sha)
        if not path.exists():
            self.misses += 1
            return None
        try:
            os.utime(path, None)
        except OSError:
            pass          # an unwritable cache still reads fine; only LRU degrades
        self.hits += 1
        return path

    def put(self, kind: str, full_name: str, sha: str, produce) -> Path:
        """Materialise the artifact via `produce(staging_path)` and install it.

        `produce` writes to a path that does not yet exist and returns nothing;
        whatever it leaves there becomes the entry.
        """
        final = self._entry(kind, full_name, sha)
        final.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=final.parent, prefix=".staging-"))
        try:
            target = staging / "artifact"
            produce(target)
            try:
                target.rename(final)
            except OSError:
                # Lost the race, or the entry appeared underneath us. Either way
                # the winner's copy is as good as ours.
                if not final.exists():
                    raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self._evict()
        return final

    # ── eviction ──────────────────────────────────────────────────────────
    def _entries(self) -> list[tuple[float, int, Path]]:
        out: list[tuple[float, int, Path]] = []
        for kind_dir in self.root.glob("*"):
            if not kind_dir.is_dir():
                continue
            for entry in kind_dir.iterdir():
                if entry.name.startswith(".staging-"):
                    continue
                try:
                    st = entry.stat()
                    size = (st.st_size if entry.is_file()
                            else sum(f.stat().st_size for f in entry.rglob("*") if f.is_file()))
                    out.append((st.st_mtime, size, entry))
                except OSError:
                    continue
        return out

    def total_bytes(self) -> int:
        return sum(size for _, size, _ in self._entries())

    def _evict(self) -> int:
        """Drop least-recently-used entries until under budget. Returns the count.

        Reports what it dropped rather than doing it silently — a cache that
        quietly discards the thing you were about to reuse looks like a
        performance regression with no cause.
        """
        entries = sorted(self._entries())          # oldest mtime first
        total = sum(size for _, size, _ in entries)
        dropped = 0
        while total > self.max_bytes and entries:
            mtime, size, path = entries.pop(0)
            try:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            except OSError:
                continue
            total -= size
            dropped += 1
            log.info("source cache: evicted %s (%.1f MB, unused %.1f h)",
                     path.name, size / 1e6, (time.time() - mtime) / 3600)
        return dropped


def local_clone(source: Path, dest: Path) -> Path:
    """`git clone --local` from a cached clone — hardlinks, no network.

    `--no-checkout` because the cached clone is treeless and the caller wants
    history, not a working tree; `--shared` is deliberately NOT used, since it
    would point the copy's objects at the cache and reintroduce exactly the
    shared-mutable-state problem this design avoids.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--local", "--no-checkout", "-q", str(source), str(dest)],
        capture_output=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return dest
