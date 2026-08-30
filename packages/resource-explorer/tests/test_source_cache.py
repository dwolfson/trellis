"""The SHA-keyed source cache — `github/source_cache.py`.

Measured 2026-08-30 on `odpi/egeria-python`: the zipball download is 23.74s and
extracting it is 0.39s; the treeless clone is 1.6s over the network and 0.28s
via `clone --local`. So the cache holds the **artifact** and every run still
extracts, or local-clones, into its own private tempdir.

That boundary is the thing these tests are really protecting. Handing callers a
shared directory would let concurrent surveys see each other's mutations, and
`git log` writes to `.git` for its own bookkeeping — a shared clone is a
corruption risk, not merely a leak.
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import pytest

from resource_explorer.github.source_cache import SourceCache, local_clone


def _cache(tmp_path, max_bytes=10 * 1024 * 1024):
    return SourceCache(cache_dir=tmp_path / "cache", max_bytes=max_bytes)


def _write(size=1024):
    def _produce(target: Path) -> None:
        target.write_bytes(b"x" * size)
    return _produce


class TestKeying:
    def test_a_miss_then_a_hit(self, tmp_path):
        c = _cache(tmp_path)
        assert c.get("zipball", "o/r", "abc123") is None
        path = c.put("zipball", "o/r", "abc123", _write())
        assert path.exists()
        assert c.get("zipball", "o/r", "abc123") == path
        assert (c.hits, c.misses) == (1, 1)

    def test_a_different_sha_is_a_different_entry(self, tmp_path):
        """The whole point. A repo-keyed cache would serve yesterday's code
        silently — the failure mode the 0.49s SHA lookup exists to rule out."""
        c = _cache(tmp_path)
        c.put("zipball", "o/r", "aaaaaaaaaaaa", _write())
        assert c.get("zipball", "o/r", "bbbbbbbbbbbb") is None

    def test_a_different_repo_is_a_different_entry(self, tmp_path):
        c = _cache(tmp_path)
        c.put("zipball", "o/one", "abc123", _write())
        assert c.get("zipball", "o/two", "abc123") is None

    def test_kinds_do_not_collide(self, tmp_path):
        """zipball and gitclone share a repo and a SHA and are different things."""
        c = _cache(tmp_path)
        c.put("zipball", "o/r", "abc123", _write())
        assert c.get("gitclone", "o/r", "abc123") is None

    def test_a_slash_in_the_repo_name_does_not_escape_the_cache_dir(self, tmp_path):
        c = _cache(tmp_path)
        path = c.put("zipball", "owner/repo", "abc123", _write())
        assert c.root.resolve() in path.resolve().parents


class TestConcurrency:
    def test_two_racers_both_succeed_and_agree(self, tmp_path):
        """Two sessions acquiring the same repo at the same instant. Both do the
        work, one wins the atomic rename, the loser discards its copy. That
        wastes a download and can never serve a torn entry, which is the right
        way round — five sessions run in this repo at once."""
        c = _cache(tmp_path)
        results, errors = [], []
        started = threading.Barrier(2)

        def _racer():
            try:
                started.wait(timeout=5)
                results.append(c.put("zipball", "o/r", "abc123", _write(4096)))
            except Exception as exc:            # noqa: BLE001 - recorded, then asserted
                errors.append(exc)

        threads = [threading.Thread(target=_racer) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=15)

        assert not errors, f"a racer raised: {errors}"
        assert len(results) == 2
        assert results[0] == results[1], "racers disagreed about the entry path"
        assert results[0].read_bytes() == b"x" * 4096, "entry is torn"

    def test_no_staging_directories_survive(self, tmp_path):
        c = _cache(tmp_path)
        c.put("zipball", "o/r", "abc123", _write())
        assert not [p for p in (c.root / "zipball").iterdir() if p.name.startswith(".staging-")]

    def test_a_failing_produce_leaves_no_entry_and_no_staging(self, tmp_path):
        """A half-written entry is worse than no entry: the next reader would
        treat it as a hit."""
        c = _cache(tmp_path)

        def _boom(target: Path) -> None:
            target.write_bytes(b"partial")
            raise RuntimeError("download died")

        with pytest.raises(RuntimeError):
            c.put("zipball", "o/r", "abc123", _boom)
        assert c.get("zipball", "o/r", "abc123") is None
        assert not [p for p in (c.root / "zipball").iterdir() if p.name.startswith(".staging-")]


class TestEviction:
    def test_it_stays_under_budget(self, tmp_path):
        c = _cache(tmp_path, max_bytes=5000)
        for i in range(10):
            c.put("zipball", "o/r", f"sha{i:09d}", _write(1000))
        assert c.total_bytes() <= 5000

    def test_least_recently_USED_goes_first_not_least_recently_written(self, tmp_path):
        """`get` touches the entry, so a repeatedly-read old entry survives a
        newly-written one. Evicting by write time would drop exactly the repo
        someone is surveying on a loop."""
        c = _cache(tmp_path, max_bytes=3500)
        old = c.put("zipball", "o/r", "old000000000", _write(1000))
        os.utime(old, (1, 1))
        c.put("zipball", "o/r", "mid000000000", _write(1000))
        c.get("zipball", "o/r", "old000000000")          # touch: now most recent
        c.put("zipball", "o/r", "new000000000", _write(1000))
        c.put("zipball", "o/r", "new200000000", _write(1000))
        assert c.get("zipball", "o/r", "old000000000") is not None
        assert c.get("zipball", "o/r", "mid000000000") is None

    def test_an_oversized_single_entry_is_not_an_infinite_loop(self, tmp_path):
        c = _cache(tmp_path, max_bytes=100)
        c.put("zipball", "o/r", "abc123", _write(5000))
        assert c.total_bytes() >= 0          # terminated at all, which is the assertion


class TestLocalClone:
    def test_it_copies_history_without_the_network(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(src), "config", "user.name", "t"], check=True)
        (src / "f.txt").write_text("hello")
        subprocess.run(["git", "-C", str(src), "add", "f.txt"], check=True)
        subprocess.run(["git", "-C", str(src), "commit", "-qm", "first"], check=True)

        dest = local_clone(src, tmp_path / "dest")
        assert (dest / ".git").exists()
        log = subprocess.run(["git", "-C", str(dest), "log", "--oneline"],
                             capture_output=True, text=True)
        assert "first" in log.stdout

    def test_the_copy_does_not_share_objects_with_the_source(self, tmp_path):
        """`--shared` would point the copy's objects at the cache and
        reintroduce exactly the shared-mutable-state problem this design
        avoids. An `alternates` file is the tell."""
        src = tmp_path / "src"
        src.mkdir()
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        subprocess.run(["git", "-C", str(src), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(src), "config", "user.name", "t"], check=True)
        (src / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(src), "add", "f.txt"], check=True)
        subprocess.run(["git", "-C", str(src), "commit", "-qm", "c"], check=True)

        dest = local_clone(src, tmp_path / "dest")
        assert not (dest / ".git" / "objects" / "info" / "alternates").exists()
