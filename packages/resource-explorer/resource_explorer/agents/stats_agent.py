"""Statistics agent — answers quantitative questions from GitHub API + SQLite time-series."""
from __future__ import annotations

import sqlite3

from resource_explorer.agents.base import BaseExplorerAgent
from resource_explorer.prompt_templates import stats_agent_system_prompt
from resource_explorer.registry import ProjectRegistry


class StatsAgent(BaseExplorerAgent):
    """
    Handles statistical queries (commits, stars, contributors, releases, LOC, etc.).
    Sources: SQLite project_stats and project_commits tables.

    Uses BeeAI tool loop — the LLM decides which tools to call based on the question,
    enabling multi-step reasoning (e.g. fetch stats, then drill into committers).
    """

    def system_prompt(self) -> str:
        return stats_agent_system_prompt()

    def tools(self) -> list:
        from resource_explorer.agents.tools import (
            query_project_stats,
            query_top_committers,
            query_commit_activity,
            query_contributor_profile,
        )
        return [query_project_stats, query_top_committers, query_commit_activity, query_contributor_profile]

    def handle(self, query: str, project_slug: str | None = None, **kwargs) -> str:
        slug = project_slug or self._infer_project_slug(query)

        if not slug:
            return self._clarification_response(query)

        prompt = f"Project: {slug}\n\nQuestion: {query}"
        try:
            return self._run_agent(prompt)
        except Exception:
            stats = self._fetch_stats(slug)
            if not stats:
                return (
                    f"No statistics available for '{slug}'. "
                    f"Run: project-explorer refresh {slug}"
                )
            from resource_explorer.llm_client import get_llm
            fallback_prompt = (
                f"{self.system_prompt()}\n\nStats data:\n{stats}\n\nQuestion: {query}\n\nAnswer:"
            )
            return get_llm().complete(fallback_prompt)

    # ── fallback data formatting ───────────────────────────────────────────────

    def _fetch_stats(self, project_slug: str | None) -> str:
        if not project_slug:
            return ""
        registry = ProjectRegistry()
        project_slug = registry._normalize_slug(project_slug)
        try:
            conn = sqlite3.connect(registry.db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM project_stats WHERE project_slug = ? ORDER BY fetched_at DESC LIMIT 1",
                (project_slug,),
            ).fetchone()
            history = conn.execute(
                "SELECT fetched_at, stars, commits_30d, forks FROM project_stats "
                "WHERE project_slug = ? ORDER BY fetched_at DESC LIMIT 4",
                (project_slug,),
            ).fetchall()
            commit_rows = conn.execute(
                "SELECT author_name, author_email, committed_at FROM project_commits "
                "WHERE project_slug = ? ORDER BY committed_at DESC",
                (project_slug,),
            ).fetchall()
            conn.close()
        except Exception:
            return ""

        if not row:
            return ""

        d = dict(row)

        def _val(key, suffix=""):
            v = d.get(key)
            return "N/A" if v is None or v == "" else f"{v}{suffix}"

        def _loc_fmt(n, exact: bool = False):
            if n is None:
                return "N/A"
            n = int(n)
            label = "" if exact else " (estimated)"
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M{label}"
            if n >= 1_000:
                return f"{n / 1_000:.1f}K{label}"
            return f"{n}{label}"

        def _size_fmt(kb):
            if kb is None:
                return "N/A"
            kb = int(kb)
            return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb} KB"

        # Prefer live counts from project_commits for consistency
        from datetime import datetime as _dt, timedelta as _td
        _now = _dt.utcnow()  # naive UTC — matches stored committed_at format
        _c30 = _c90 = 0
        try:
            _conn2 = sqlite3.connect(registry.db_path)
            _c30 = _conn2.execute(
                "SELECT COUNT(*) FROM project_commits WHERE project_slug = ? AND committed_at >= ?",
                (project_slug, (_now - _td(days=30)).isoformat()),
            ).fetchone()[0]
            _c90 = _conn2.execute(
                "SELECT COUNT(*) FROM project_commits WHERE project_slug = ? AND committed_at >= ?",
                (project_slug, (_now - _td(days=90)).isoformat()),
            ).fetchone()[0]
            _conn2.close()
        except Exception:
            pass
        commits_30d = _c30 if (_c30 or _c90) else (d.get("commits_30d") or 0)
        commits_90d = _c90 if (_c30 or _c90) else (d.get("commits_90d") or 0)

        lines = [
            f"Project: {project_slug}",
            "",
            "── Repository ──────────────────────────",
            f"  License:            {_val('license')}",
            f"  Topics:             {_val('topics') or 'none'}",
            f"  Created:            {(_val('repo_created_at') or '')[:10] or 'N/A'}",
            f"  Last pushed:        {(_val('last_pushed_at') or '')[:10] or 'N/A'}",
            f"  Size:               {_size_fmt(d.get('repo_size_kb'))}",
            f"  Primary language:   {_val('primary_language')}",
            "",
            "── Code ────────────────────────────────",
            f"  Files:              {self._indexed_file_count(project_slug, registry)}",
            f"  Lines of code:      {_loc_fmt(d.get('ingestion_lines_of_code'), exact=True) if d.get('ingestion_lines_of_code') is not None else _loc_fmt(d.get('lines_of_code'))}",
            f"  Language breakdown: {_val('language_breakdown')}",
            "",
            "── Community ───────────────────────────",
            f"  Stars:              {_val('stars')}",
            f"  Forks:              {_val('forks')}",
            f"  Watchers:           {_val('watchers')}",
            f"  Contributors:       {_val('contributors_count')}",
            f"  Open issues:        {_val('open_issues')}",
            "",
            "── Activity ────────────────────────────",
            f"  Commits (30 days):  {commits_30d}",
            f"  Commits (90 days):  {commits_90d}",
            "",
            "── Releases ────────────────────────────",
            f"  Total releases:     {_val('releases_count')}",
            f"  Latest release:     {_val('latest_release')}",
            f"  Latest release at:  {(_val('latest_release_at') or '')[:10] or 'N/A'}",
            f"  Avg interval:       {_val('avg_release_interval_days', ' days')}",
            "",
            f"Stats as of: {(_val('fetched_at') or '')[:19] or 'N/A'}",
        ]

        if len(history) > 1:
            oldest, newest = dict(history[-1]), dict(history[0])
            star_diff = (newest.get("stars") or 0) - (oldest.get("stars") or 0)
            fork_diff = (newest.get("forks") or 0) - (oldest.get("forks") or 0)
            since = (oldest.get("fetched_at") or "")[:10]
            if star_diff or fork_diff:
                lines += ["", f"Trends since {since}:"]
                if star_diff:
                    lines.append(f"  Stars: {'+' if star_diff > 0 else ''}{star_diff}")
                if fork_diff:
                    lines.append(f"  Forks: {'+' if fork_diff > 0 else ''}{fork_diff}")

        commit_section = self._format_commit_trends(commit_rows)
        if commit_section:
            lines += ["", commit_section]

        return "\n".join(lines)

    def _indexed_file_count(self, slug: str, registry) -> str:
        """Return total file count — prefers survey total, falls back to code-only count."""
        try:
            conn = sqlite3.connect(registry.db_path)
            # Prefer survey total (all file types across all collections)
            n = conn.execute(
                """SELECT SUM(file_count) FROM project_file_type_counts
                   WHERE project_slug = ?
                     AND surveyed_at = (
                         SELECT MAX(surveyed_at) FROM project_file_type_counts WHERE project_slug = ?
                     )""",
                (slug, slug),
            ).fetchone()[0]
            if n:
                conn.close()
                return f"{n} (surveyed)"
            # Fall back to code-symbols count (Python/JS/Java/Go only)
            n = conn.execute(
                "SELECT COUNT(DISTINCT file_path) FROM project_code_symbols WHERE project_slug = ?",
                (slug,),
            ).fetchone()[0]
            conn.close()
            if n:
                return f"{n} (code files only — run survey for full count)"
        except Exception:
            pass
        d = getattr(self, '_last_stats_row', {})
        if d.get('ingestion_file_count') is not None:
            return str(d['ingestion_file_count'])
        v = d.get('file_count')
        return str(v) if v is not None else "N/A"

    def _format_commit_trends(self, commit_rows) -> str:
        from collections import Counter, defaultdict
        from datetime import datetime

        if not commit_rows:
            return (
                "── Commit Trends ───────────────────────\n"
                "  No commit data. Run: project-explorer refresh <slug>"
            )

        rows = [dict(r) for r in commit_rows]
        total = len(rows)

        author_counts: Counter = Counter()
        for r in rows:
            name = r.get("author_name") or r.get("author_email") or "unknown"
            author_counts[name] += 1
        top = author_counts.most_common(5)

        now = datetime.utcnow()
        week_counts: defaultdict = defaultdict(int)
        for r in rows:
            ts = r.get("committed_at", "")
            try:
                dt = datetime.fromisoformat(ts[:19])  # strip tz suffix — stored as naive UTC
                weeks_ago = (now - dt).days // 7
                if weeks_ago < 12:
                    week_counts[weeks_ago] += 1
            except Exception:
                pass

        lines = ["── Commit Trends (last 90 days) ────────"]
        lines.append(f"  Total commits stored: {total}")
        lines.append("")
        lines.append("  Top committers:")
        for name, count in top:
            lines.append(f"    {name}: {count}")

        if week_counts:
            lines.append("")
            lines.append("  Weekly activity (most recent first):")
            for week in sorted(week_counts):
                label = f"{'this week' if week == 0 else f'{week}w ago':>9}"
                bar = "█" * min(week_counts[week], 20)
                lines.append(f"    {label}: {bar} {week_counts[week]}")

        return "\n".join(lines)
