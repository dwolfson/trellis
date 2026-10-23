"""A repository's contributors, two lists, from the GitHub API (BRIEF-CONTRIBUTORS-GITHUB.md, owner 2026-10-23).

* `months_12`  commits in the last 365 days, counted by git author (GitHub login when GitHub links the email,
               otherwise the git author's email or name), from `GET /repos/{o}/{r}/commits?since=..&per_page=100`.
* `all_time`   GitHub's own contributions per linked account, from
               `GET /repos/{o}/{r}/contributors?per_page=100&anon=1` (anonymous rows kept as Anonymous).

The two lists count differently, and every surface says so in one line (`COMPARE_WORDS`).

**Cost (calls per repository per fetch).** One REST call per 100 commits in the window for `months_12`, one per
100 contributor rows for `all_time`, each capped at `MAX_CALLS` (50: the most recent 5,000 commits, the first
5,000 rows); plus one rate-limit read before the first call (GitHub does not count that read). A capped list says
so (`capped` holds where it stopped) and the card says "12-month list from the most recent 5,000 commits (window
cut at <date>)". A 403 (or any refusal) stops the list cleanly: `not_permitted` with the reset time, and NOTHING
is written for that list, so a partial list is never stored or shown as whole.

**Storage.** `project_contributors` (registry `PROJECT_CONTRIBUTORS_DDL`), one fetch per (repository, list) kept
with its rows; rank 0 is the fetch's own row, so "fetched, nothing there" is stored and "never fetched" is the
absence of rows. `contributors()` is the ONE reader: the question page's compile, the chat tool, chaoss_metrics
and the publish step all read through it.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

WINDOW_12 = "months_12"
WINDOW_ALL = "all_time"
WINDOWS = (WINDOW_12, WINDOW_ALL)
SOURCE = {WINDOW_12: "github:commits", WINDOW_ALL: "github:contributors"}
SHARE_BASIS = {WINDOW_12: "commits in window", WINDOW_ALL: "contributions all time"}
LOOKBACK_12 = 365
PER_PAGE = 100
#: Calls per list per fetch: 50 pages of 100 = the most recent 5,000 commits (or the first 5,000 rows).
MAX_CALLS = 50
#: GitHub links only the first 500 author email addresses of a repository to accounts; the rest come back anonymous.
LINKING_LIMIT = 500
FETCHES_KEPT = 5
TOP = 10

NO_FETCH_YET = "no_fetch_yet"
EMPTY_REPOSITORY = "empty_repository"
NOT_PERMITTED = "not_permitted"
LINKING_LIMIT_REACHED = "linking_limit"

NO_FETCH_WORDS = "no contributor fetch yet"
EMPTY_12_WORDS = "no commits in the last 12 months"
#: The brief gives no words for an all-time list GitHub answers empty; this says what was read.
EMPTY_ALL_WORDS = "GitHub lists no contributors"
COMPARE_WORDS = ("12-month list counts commits by git author in the window; all-time list counts GitHub's "
                 "contributions by linked account. Shares are not comparable across the two.")
FALLBACK_WORDS = "from git authors, 90-day fetch"


def not_permitted_words(reset_at: str) -> str:
    return f"GitHub refused the read (rate limit resets {reset_at})" if reset_at else "GitHub refused the read"


def linking_words(anonymous: int) -> str:
    return f"GitHub links only the first {LINKING_LIMIT} authors; {anonymous} more are anonymous"


def capped_words(cut_at: str) -> str:
    return (f"12-month list from the most recent {MAX_CALLS * PER_PAGE:,} commits "
            f"(window cut at {(cut_at or '')[:10]})")


def bots_words(n: int) -> str:
    return f"{n} bot{'s' if n != 1 else ''} excluded"


@dataclass
class ContributorRow:
    id: int
    rank: int
    login: str
    display_name: str
    author_email: str
    commits: int
    share: float
    is_bot: bool
    #: User | Bot | Anonymous (all_time, as GitHub types them) or User | Bot | unlinked (months_12: a git author
    #: GitHub could not link to an account).
    kind: str

    @property
    def name(self) -> str:
        return self.login or self.display_name or self.author_email or "unknown"

    def as_dict(self) -> dict:
        return {"rank": self.rank, "login": self.login, "name": self.name, "display_name": self.display_name,
                "commits": self.commits, "share": round(self.share, 4), "is_bot": self.is_bot, "kind": self.kind}


@dataclass
class ContributorList:
    slug: str
    window: str
    rows: list = field(default_factory=list)          # the top N (bots excluded unless asked), by rank
    share_basis: str = ""
    fetched_at: str = ""
    lookback_days: int | None = None
    capped: bool = False
    cut_at: str = ""                                   # where the cap stopped the list ('' when read whole)
    bots_excluded: int = 0
    absence: str = ""                                  # '' or one of the four absences
    reset_at: str = ""                                 # with not_permitted
    total: int = 0                                     # commits (months_12) / contributions (all_time) counted
    total_rows: int = 0                                # contributor rows stored, bots and anonymous included
    anonymous: int = 0
    #: Every stored row id behind `rows` plus the fetch's own row: what a surface that rendered this list saw.
    row_ids: list = field(default_factory=list)

    @property
    def top_share(self) -> float:
        """The shown rows' share of the TOTAL (not of the shown rows)."""
        return sum(r.share for r in self.rows)

    def top_n_share(self, n: int) -> float:
        return sum(r.share for r in self.rows[:n])

    def words(self) -> list[str]:
        """The card's lines for this list, in the brief's words: absence first, then the cut, the bots, the
        linking limit."""
        out: list[str] = []
        if self.absence == NO_FETCH_YET:
            return [NO_FETCH_WORDS]
        if self.absence == NOT_PERMITTED:
            return [not_permitted_words(self.reset_at)]
        if self.absence == EMPTY_REPOSITORY:
            return [EMPTY_12_WORDS if self.window == WINDOW_12 else EMPTY_ALL_WORDS]
        if self.capped and self.window == WINDOW_12:
            out.append(capped_words(self.cut_at))
        elif self.capped:
            out.append(f"all-time list from the first {MAX_CALLS * PER_PAGE:,} rows GitHub returned")
        if self.bots_excluded:
            out.append(bots_words(self.bots_excluded))
        if self.absence == LINKING_LIMIT_REACHED:
            out.append(linking_words(self.anonymous))
        return out

    def as_dict(self) -> dict:
        return {"window": self.window, "rows": [r.as_dict() for r in self.rows], "share_basis": self.share_basis,
                "fetched_at": self.fetched_at, "lookback_days": self.lookback_days, "capped": self.capped,
                "cut_at": self.cut_at, "bots_excluded": self.bots_excluded, "absence": self.absence,
                "reset_at": self.reset_at, "total": self.total, "total_rows": self.total_rows,
                "top_share": round(self.top_share, 4), "words": self.words()}


def _kind(window: str, login: str, is_bot: bool) -> str:
    if is_bot:
        return "Bot"
    if login:
        return "User"
    return "Anonymous" if window == WINDOW_ALL else "unlinked"


def contributors(registry, slug: str, window: str, top: int = TOP, *, include_bots: bool = False) -> ContributorList:
    """The newest stored fetch of one list. `rows` is the top `top` (bots left out unless `include_bots`); shares
    are each row's part of the whole list's total, so the top-N share is reported against the total."""
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {WINDOWS}, not {window!r}")
    out = ContributorList(slug=slug, window=window, share_basis=SHARE_BASIS[window])
    stored = registry.latest_contributor_fetch(slug, window)
    if not stored:
        out.absence = NO_FETCH_YET
        return out
    head = stored[0] if stored[0]["rank"] == 0 else None
    people = [r for r in stored if r["rank"] >= 1]
    first = head or stored[0]
    out.fetched_at = first["fetched_at"]
    out.lookback_days = first["lookback_days"]
    out.cut_at = first["capped"] or ""
    out.capped = bool(out.cut_at)
    out.total = int(head["commits"]) if head else sum(int(r["commits"]) for r in people)
    out.total_rows = len(people)
    rows = [ContributorRow(id=int(r["id"]), rank=int(r["rank"]), login=r["login"] or "",
                           display_name=r["display_name"] or "", author_email=r["author_email"] or "",
                           commits=int(r["commits"]), share=float(r["share"]), is_bot=bool(r["is_bot"]),
                           kind=_kind(window, r["login"] or "", bool(r["is_bot"]))) for r in people]
    out.bots_excluded = sum(1 for r in rows if r.is_bot) if not include_bots else 0
    shown = [r for r in rows if include_bots or not r.is_bot][:max(top, 0)]
    out.rows = shown
    out.row_ids = ([int(head["id"])] if head else []) + [r.id for r in shown]
    if not people:
        out.absence = EMPTY_REPOSITORY
        return out
    out.anonymous = sum(1 for r in rows if r.kind == "Anonymous")
    if window == WINDOW_ALL and out.anonymous and len(people) > LINKING_LIMIT:
        out.absence = LINKING_LIMIT_REACHED
    return out


# ── the fetch ───────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class FetchOutcome:
    window: str
    absence: str = ""
    reset_at: str = ""
    pages: int = 0
    rows: int = 0
    total: int = 0
    capped: str = ""
    row_ids: list = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class _Refused(Exception):
    def __init__(self, reset_at: str, message: str) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class _Empty(Exception):
    pass


def _reset_from_headers(headers) -> str:
    raw = (headers or {}).get("x-ratelimit-reset") or (headers or {}).get("X-RateLimit-Reset")
    if not raw:
        return ""
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return str(raw)


def _get(client, path: str, params: dict):
    """One call. A refusal (401/403/429) becomes _Refused with the reset time; 409 (GitHub's answer for the commits
    of an empty repository) becomes _Empty; anything else propagates."""
    from github import GithubException

    try:
        headers, data = client.rest_get(path, params)
    except GithubException as exc:
        if exc.status in (401, 403, 429):
            raise _Refused(_reset_from_headers(exc.headers), str(exc)) from exc
        if exc.status == 409:
            raise _Empty(str(exc)) from exc
        raise
    return headers, data


def _is_bot_login(user: dict | None) -> bool:
    if not user:
        return False
    return (user.get("type") == "Bot") or str(user.get("login") or "").endswith("[bot]")


def _shares(rows: list[dict], total: int) -> list[dict]:
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["share"] = (r["commits"] / total) if total else 0.0
    return rows


def estimate_pages(registry, slug: str, window: str) -> tuple[int, str]:
    """Calls this list's next fetch should take, and on what basis: the previous fetch's count, else the
    repository's own counts (`project_stats`), else one call."""
    prev = registry.latest_contributor_fetch(slug, window)
    if prev:
        n = int(prev[0]["commits"]) if window == WINDOW_12 and prev[0]["rank"] == 0 else \
            len([r for r in prev if r["rank"] >= 1])
        basis = "the previous fetch"
    else:
        stats = {}
        try:
            stats = registry.get_latest_project_stats(slug) or {}
        except Exception:  # noqa: BLE001
            stats = {}
        if window == WINDOW_12:
            n = stats.get("commits_365d") or (4 * (stats.get("commits_90d") or 0))
        else:
            n = stats.get("contributors_count") or 0
        basis = "the repository's commit count" if window == WINDOW_12 else "the repository's contributor count"
        if not n:
            return 1, "no count recorded"
    return min(MAX_CALLS, max(1, math.ceil(n / PER_PAGE))), basis


def cost_line(registry, slug: str) -> str:
    """The line shown before a fetch: the calls both lists should take."""
    p12, b12 = estimate_pages(registry, slug, WINDOW_12)
    pall, ball = estimate_pages(registry, slug, WINDOW_ALL)
    return (f"about {p12 + pall} GitHub call(s): 12-month list {p12} (from {b12}), all-time list {pall} "
            f"(from {ball}); at most {MAX_CALLS} each")


def _fetch_12(client, full_name: str, now: datetime) -> tuple[list[dict], int, int, str]:
    since = (now - timedelta(days=LOOKBACK_12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_key: dict[str, dict] = {}
    total = pages = 0
    oldest = ""
    last_full = False
    for page in range(1, MAX_CALLS + 1):
        try:
            _, data = _get(client, f"/repos/{full_name}/commits",
                           {"since": since, "per_page": PER_PAGE, "page": page})
        except _Empty:
            data = []
        pages += 1
        data = data or []
        for c in data:
            git_author = (c.get("commit") or {}).get("author") or {}
            user = c.get("author") or None                     # GitHub's linked account, null when unlinked
            login = (user or {}).get("login") or ""
            email = (git_author.get("email") or "").strip()
            name = (git_author.get("name") or "").strip()
            key = f"login:{login.lower()}" if login else (f"email:{email.lower()}" if email else f"name:{name.lower()}")
            entry = by_key.setdefault(key, {"login": login, "display_name": name, "author_email": email,
                                            "commits": 0, "is_bot": False})
            entry["commits"] += 1
            entry["is_bot"] = entry["is_bot"] or _is_bot_login(user) or name.endswith("[bot]")
            total += 1
            date = git_author.get("date") or ""
            if date and (not oldest or date < oldest):
                oldest = date
        last_full = len(data) >= PER_PAGE
        if not last_full:
            break
    capped = oldest if (pages >= MAX_CALLS and last_full) else ""
    rows = sorted(by_key.values(), key=lambda r: (-r["commits"], (r["login"] or r["author_email"]).lower()))
    return _shares(rows, total), total, pages, capped


def _fetch_all(client, full_name: str) -> tuple[list[dict], int, int, str]:
    rows: list[dict] = []
    pages = 0
    last_full = False
    for page in range(1, MAX_CALLS + 1):
        _, data = _get(client, f"/repos/{full_name}/contributors", {"per_page": PER_PAGE, "anon": 1, "page": page})
        pages += 1
        data = data or []                                  # 204 No Content: an empty repository
        for c in data:
            anonymous = c.get("type") == "Anonymous"
            login = "" if anonymous else (c.get("login") or "")
            name = (c.get("name") or "") if anonymous else ""
            email = (c.get("email") or "") if anonymous else ""
            rows.append({"login": login, "display_name": name, "author_email": email,
                         "commits": int(c.get("contributions") or 0),
                         "is_bot": (not anonymous and _is_bot_login(c)) or "[bot]" in (name + email)})
        last_full = len(data) >= PER_PAGE
        if not last_full:
            break
    capped = f"rows {len(rows)}" if (pages >= MAX_CALLS and last_full) else ""
    total = sum(r["commits"] for r in rows)
    rows.sort(key=lambda r: -r["commits"])                # GitHub's own order is by contributions; kept stable
    return _shares(rows, total), total, pages, capped


def fetch_contributors(registry, client, slug: str, full_name: str, *, now: datetime | None = None) -> dict:
    """Fetch both lists for one repository and store each one whole, or not at all.

    `client` is a GitHubClient (its `rest_get` and `check_rate_limit`); `full_name` is "owner/repo". Returns
    {window: FetchOutcome.as_dict()} plus "cost_line" (the estimate made before the first call)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    fetched_at = now.isoformat()
    result: dict = {"cost_line": cost_line(registry, slug)}
    log.info("contributors %s: %s", slug, result["cost_line"])
    try:
        rate = client.check_rate_limit()
    except Exception:  # noqa: BLE001 - optimistic, as the commits fetch is
        rate = None
    for window, fetch in ((WINDOW_12, lambda: _fetch_12(client, full_name, now)),
                          (WINDOW_ALL, lambda: _fetch_all(client, full_name))):
        outcome = FetchOutcome(window)
        need, _ = estimate_pages(registry, slug, window)
        if rate is not None and int(rate.get("remaining") or 0) < need:
            outcome.absence, outcome.reset_at = NOT_PERMITTED, str(rate.get("reset_at") or "")[:19]
            result[window] = outcome.as_dict()
            continue
        try:
            rows, total, pages, capped = fetch()
        except _Refused as exc:
            outcome.absence, outcome.reset_at, outcome.error = NOT_PERMITTED, exc.reset_at, str(exc)[:300]
            result[window] = outcome.as_dict()
            continue
        except Exception as exc:  # noqa: BLE001 - one list failing never writes a partial list
            outcome.error = f"{type(exc).__name__}: {exc}"[:300]
            result[window] = outcome.as_dict()
            continue
        outcome.pages, outcome.rows, outcome.total, outcome.capped = pages, len(rows), total, capped
        outcome.row_ids = registry.write_contributor_fetch(
            slug, window, fetched_at, rows, total=total,
            lookback_days=LOOKBACK_12 if window == WINDOW_12 else None,
            source=SOURCE[window], capped=capped, keep_fetches=FETCHES_KEPT)
        if not rows:
            outcome.absence = EMPTY_REPOSITORY
        result[window] = outcome.as_dict()
    return result


# ── what the surfaces show ──────────────────────────────────────────────────────────────────────────────────────


def both(registry, slug: str, top: int = TOP) -> dict:
    return {w: contributors(registry, slug, w, top) for w in WINDOWS}


def headline_sentence(lists: dict) -> str:
    """Names the top contributor and the top-3 share: the all-time list when there is one, else the 12-month."""
    for window in (WINDOW_ALL, WINDOW_12):
        cl = lists.get(window)
        if cl is None or cl.absence in (NO_FETCH_YET, NOT_PERMITTED, EMPTY_REPOSITORY) or not cl.rows:
            continue
        top = cl.rows[0]
        span = "all time" if window == WINDOW_ALL else "in the last 12 months"
        return (f"top contributor {top.name} ({top.share:.0%} of {cl.share_basis}); "
                f"top 3 hold {cl.top_n_share(3):.0%} {span}")
    return ""


def text_block(lists: dict, *, limit: int = TOP) -> list[str]:
    """The lists as lines a model or a person reads (the compile's extent and the chat tool's answer)."""
    lines = ["contributors:"]
    for window, label in ((WINDOW_ALL, "all time (GitHub contributions by linked account)"),
                          (WINDOW_12, "last 12 months (commits by git author)")):
        cl = lists[window]
        words = cl.words()
        if not cl.rows:
            lines.append(f"- {label}: {'; '.join(words) or NO_FETCH_WORDS}")
            continue
        shown = cl.rows[:limit]
        lines.append(f"- {label}, fetched {cl.fetched_at[:10]}: top {len(shown)} of {cl.total_rows} hold "
                     f"{sum(r.share for r in shown):.0%} of {cl.total} {cl.share_basis}"
                     + (f" ({'; '.join(words)})" if words else ""))
        for r in shown:
            extra = f" [{r.kind}]" if r.kind not in ("User",) else ""
            lines.append(f"  {r.rank}. {r.name}{extra}: {r.commits} ({r.share:.1%})")
    lines.append(f"- {COMPARE_WORDS}")
    return lines


def annotations(registry, slug: str) -> list:
    """ONE ResourceMeasureAnnotation per stored list (Egeria has no contributor annotation type; following its lead
    as far as it goes): annotationType "Contributors", `resourceProperties` top10 as JSON, `measurementName` the
    window, `as_of` the fetch time, `basis` the share basis. Identified by (check_name, item_key = window), so a
    second publish of the same report reuses the same qualifiedName (read-first per report and window). A list
    never fetched, refused or empty publishes nothing."""
    from resource_explorer.surveyors.survey_report import ResourceMeasureAnnotation

    out = []
    for window in WINDOWS:
        cl = contributors(registry, slug, window)
        if not cl.rows:
            continue
        top10 = [{"login": r.name, "commits": r.commits, "share": round(r.share, 4)} for r in cl.rows]
        out.append(ResourceMeasureAnnotation(
            summary=(f"Contributors, {'last 12 months' if window == WINDOW_12 else 'all time'}: "
                     + ", ".join(r.name for r in cl.rows[:3])),
            analysis_step="repo_chaoss_metrics", annotation_type_name="Contributors",
            check_name="contributors", item_key=window,
            explanation="; ".join([COMPARE_WORDS, *cl.words()]),
            confidence=100,
            resource_properties={"top10": json.dumps(top10)},
            additional_properties={"measurementName": window, "as_of": cl.fetched_at, "basis": cl.share_basis,
                                   "source": SOURCE[window], "total": str(cl.total),
                                   "capped": cl.cut_at, "bots_excluded": str(cl.bots_excluded)}))
    return out
