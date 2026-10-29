"""Storage for portals, directories and imported datasets, over the shared registry's connection.

Values an adapter did not report are stored as the text `not_reported` (never ''), booleans as 'true'/'false', so
a column never holds a bare absence. `record_json` is the publisher's record verbatim.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from resource_explorer.open_data.absence import NOT_REPORTED


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    """Lower-case, underscores: the registry's own slug shape (`ProjectRegistry._normalize_slug`)."""
    out = re.sub(r"[^a-z0-9.]+", "_", (text or "").lower()).strip("_")
    return out or "unnamed"


def normalise_url(url: str) -> str:
    """For 'is this already registered': scheme-less, lower-case host, no trailing slash, no www."""
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _enc(value) -> str:
    return NOT_REPORTED if value == NOT_REPORTED else ("true" if value is True else "false" if value is False else str(value))


def _dec_flag(text: str):
    return {"true": True, "false": False}.get(text, NOT_REPORTED)


class OpenDataStore:
    def __init__(self, registry=None):
        from resource_explorer.registry import ProjectRegistry

        self.registry = registry or ProjectRegistry()

    def _conn(self):
        return self.registry._conn()

    # ── portals ──────────────────────────────────────────────────────────
    def portal_exists(self, slug: str) -> bool:
        return self.get_portal(slug) is not None

    def add_portal(self, *, slug: str, display_name: str, api_kind: str, base_url: str, secret_ref: str = "",
                   origin: str = "hand", registered_by: str = "", adapter: str = "",
                   calls_per_page: int | None = None, page_size: int | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO open_data_portals (slug, display_name, api_kind, base_url, secret_ref, origin,"
                " registered_by, registered_at, adapter, calls_per_page, page_size)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, display_name, api_kind, base_url, secret_ref, origin, registered_by, now(), adapter,
                 calls_per_page, page_size))

    def get_portal(self, slug: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM open_data_portals WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None

    def list_portals(self) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM open_data_portals ORDER BY display_name").fetchall()]

    def portal_by_url(self, url: str) -> dict | None:
        want = normalise_url(url)
        return next((p for p in self.list_portals() if normalise_url(p["base_url"]) == want), None)

    def remove_portal(self, slug: str) -> int:
        with self._conn() as conn:
            return conn.execute("DELETE FROM open_data_portals WHERE slug = ?", (slug,)).rowcount

    # ── directories ──────────────────────────────────────────────────────
    def add_directory(self, *, slug: str, display_name: str, api_kind: str, base_url: str,
                      registered_by: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO portal_directories (slug, display_name, api_kind, base_url, registered_by,"
                " registered_at, last_run_at) VALUES (?, ?, ?, ?, ?, ?, '')",
                (slug, display_name, api_kind, base_url, registered_by, now()))

    def get_directory(self, slug: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM portal_directories WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None

    def list_directories(self) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM portal_directories ORDER BY display_name").fetchall()]

    def touch_directory_run(self, slug: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE portal_directories SET last_run_at = ? WHERE slug = ?", (now(), slug))

    # ── datasets ─────────────────────────────────────────────────────────
    def dataset_by_identifier(self, identifier: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM open_data WHERE identifier = ?", (identifier,)).fetchone()
        return self._dataset(row) if row else None

    def get_dataset(self, slug: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM open_data WHERE slug = ?", (slug,)).fetchone()
        return self._dataset(row) if row else None

    def list_datasets(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM open_data ORDER BY imported_at DESC, slug").fetchall()
        return [self._dataset(r) for r in rows]

    def add_dataset(self, *, slug: str, row: dict, portals: list[str], retrieved_at: str, imported_by: str,
                    work_list_slug: str, datacite: dict | None) -> None:
        """`row` is an adapter's normalised candidate row (its `record` is the verbatim publisher record)."""
        flags = row["licence"]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO open_data (slug, identifier, identifier_kind, portal_slug, portals_json, title,"
                " publisher, licence_id, attribution, share_alike, commercial, modified, formats_json,"
                " size_bytes, record_json, retrieved_at, datacite_json, imported_by, imported_at, work_list_slug)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, row["identifier"], row["identifier_kind"], portals[0], json.dumps(portals),
                 _enc(row["title"]), _enc(row["publisher"]), _enc(row["licence_id"]),
                 _enc(flags["attribution"]), _enc(flags["share_alike"]), _enc(flags["commercial"]),
                 _enc(row["modified"]), json.dumps(row["formats"]), _enc(row["size"]),
                 json.dumps(row["record"]), retrieved_at, json.dumps(datacite) if datacite else "",
                 imported_by, now(), work_list_slug))

    @staticmethod
    def _dataset(row) -> dict:
        d = dict(row)
        d["portals"] = json.loads(d.pop("portals_json") or "[]")
        d["formats"] = json.loads(d.pop("formats_json"))
        d["record"] = json.loads(d.pop("record_json"))
        d["datacite"] = json.loads(d.pop("datacite_json")) if d.get("datacite_json") else None
        d.pop("datacite_json", None)
        d["licence"] = {"attribution": _dec_flag(d.pop("attribution")), "share_alike": _dec_flag(d.pop("share_alike")),
                        "commercial": _dec_flag(d.pop("commercial"))}
        d["size"] = d.pop("size_bytes")
        return d
