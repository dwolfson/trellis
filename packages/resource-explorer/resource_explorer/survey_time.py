"""When evidence was produced: the one way survey times are written (BRIEF-CONTEXT-SECTION-AS-OF.md, PR B).

A survey time says when an analysis result was produced. The context compile packs it as each section's as-of,
and the closed-loop diagnosis ages it. Until 2026-11 these times were written by `datetime.utcnow().isoformat()`:
UTC by construction, but without a zone, so nothing downstream could tell them from local time and the diagnosis
correctly refused to read them. They are now written with a zone (`+00:00`).

Stored values keep their form: old rows stay without a zone and are reported as unreadable, never assumed to be
UTC at read time. Rows of both forms order correctly as strings (the fixed-width date and time come first), so
`MAX(surveyed_at)` still picks the latest run.

`SurveyResult.surveyed_at`, the datetime Egeria's SurveyReport and Annotation qualified names are built from,
stays naive on purpose: it names Egeria elements, and a kept survey published later must produce the same name
as the live publish of the same run (`survey_snapshot.to_result` strips the zone back off).
"""
from __future__ import annotations

from datetime import UTC, datetime


def now_utc() -> datetime:
    """The current time, in UTC, with its zone."""
    return datetime.now(UTC)


def now_utc_iso() -> str:
    """The current time as an ISO string with a zone, e.g. `2026-11-10T12:00:00.123456+00:00`."""
    return now_utc().isoformat()


def as_utc_iso(moment: datetime) -> str:
    """`moment` as an ISO string with a zone. A naive datetime is taken to be UTC: callers pass only values they
    made with `datetime.utcnow()`, never a local time."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()
