# Automate / Notification Manager — pyegeria convenience API spec

**Status: specification only, not implemented. Written per explicit direction
(2026-08-13): "define what we want pyegeria/egeria to do and then I can add
it" — this is that definition, not an attempt to build it live.**

## Why this exists

Part 4 of `docs/discovery-automate-project-context-plan.md` (Automate, the
8th canonical intent) is built local-first: RE's own `notification_subscriptions`
table + `scheduler.py`'s change-detection + RFA delivery, all real and
working today (see that plan doc and `resource_explorer/notification_detector.py`).
What's deliberately **not** built is the Egeria-side catalog-of-record piece —
creating a real `NotificationType` element, linking it to the monitored
resource and subscriber via Egeria's own Notification Manager OMVS. This
doc specifies what pyegeria would need to expose for that to be safe to
build, so it can be added deliberately rather than guessed at live.

## What's already real and safe to use today

Confirmed by reading `pyegeria/omvs/notification_manager.py` directly —
these are dedicated, non-generic methods, already fine to call once
Notification Type creation itself is sorted:

- `NotificationManager.link_monitored_resource(...)`
- `NotificationManager.detach_monitored_resource(...)`
- `NotificationManager.link_notification_subscriber(...)`
- `NotificationManager.detach_notification_subscriber(...)`

## The gap: no dedicated "create a Notification Type" method

Dr.Egeria's own "Create Notification Type" command exists — confirmed via
`pyegeria/view/dr_egeria_reports.py`'s `'Notification-Type-DrE-Advanced'`
FormatSet, which lists real NotificationType-specific columns:

- `notification_interval`
- `minimum_notification_interval`
- `next_scheduled_notification`
- `notification_count`
- `multiple_notifications_permitted`
- `planned_start_date` / `planned_completion_date`

...plus the generic `GovernanceDefinition` attributes every governance
definition carries (`domain_identifier`, `scope`, `importance`,
`implications`, `outcomes`, `results`, `summary`, `usage`,
`implementation_description`, etc.).

But there is **no dedicated pyegeria method** backing that command — it
goes through `GovernanceOfficer.create_governance_definition(body)`, a
fully generic call keyed by a `"typeName"` string in the request body.
That method's own docstring enumerates the definition types it documents
usage for — `BusinessImperative`, `RegulationArticle`, `Threat`,
`GovernancePrinciple`, `GovernanceObligation`, `GovernanceApproach`,
`GovernanceProcessingPurpose` — **`NotificationType` is not among them.**
The FormatSet proves the columns exist somewhere server-side; it does not
prove what `typeName` value or properties-class name
(`create_governance_definition`'s docstring shows a
`GovernanceDefinitionProperties`/`GovernanceStrategyProperties`/
`RegulationProperties`/... table, one row per definition type — the
NotificationType row is simply missing from what's documented) the request
body actually needs. Getting this wrong silently creates a malformed or
wrong-typed element — exactly the failure mode CLAUDE.md rule 12 warns
against reimplementing untested, and why this is a spec, not an attempt.

## Proposed API

A thin, dedicated wrapper — same shape as `link_monitored_resource` etc.,
not a new generic-body escape hatch:

```python
def create_notification_type(
    self,
    display_name: str,
    description: str = "",
    summary: str = "",
    *,
    notification_interval: str | None = None,        # ISO 8601 duration, e.g. "P1D"
    minimum_notification_interval: str | None = None,
    multiple_notifications_permitted: bool = True,
    planned_start_date: str | None = None,
    planned_completion_date: str | None = None,
    domain_identifier: int = 0,
    additional_properties: dict[str, str] | None = None,
) -> str:
    """Create a NotificationType governance definition. Returns its GUID.

    NEEDS LIVE VERIFICATION before shipping: the exact `typeName` value
    and properties-class name NotificationType actually requires in
    create_governance_definition()'s body — not in that method's own
    docstring today. Confirm via a live create + read-back against a
    disposable qualified_name, comparing the read-back typeName/
    properties shape against what Create Notification Type's own
    Dr.Egeria markdown command produces for the same inputs (the
    known-good reference implementation)."""
```

```python
def find_notification_types(
    self, search_string: str = "*", *, active_only: bool = False,
) -> list[dict]:
    """Real Notification Types matching a search. Thin wrapper over
    GovernanceOfficer.find_governance_definitions() — needs confirming
    live whether find_constraints={"metadata_element_type": "NotificationType"}
    actually filters by classification (the plan doc's own assumption,
    never verified against a live server) or needs a different constraint
    shape (e.g. filtering client-side on the returned typeName instead)."""
```

```python
def update_notification_type(self, guid: str, **fields) -> None:
    """No Dr.Egeria command and no confirmed pyegeria method exist for
    this today (link/detach only). A real gap — a NotificationType's
    interval/description can currently only be set at creation."""
```

```python
def list_monitored_resources(self, notification_type_guid: str) -> list[dict]:
    """Convenience listing — today you'd fetch the full element with
    related elements expanded and filter client-side; no dedicated
    reader exists. Same gap for the subscriber side:"""

def list_notification_subscribers(self, notification_type_guid: str) -> list[dict]:
    ...
```

## What RE would do once this lands

`notification_subscriptions.egeria_notification_type_guid`/
`egeria_notification_type_qualified_name` (already columns on that table,
currently always empty) get populated by calling
`create_notification_type()` + `link_monitored_resource()` +
`link_notification_subscriber()` at subscription-creation time, mirroring
exactly how `EgeriaPublisher` already creates/finds a `SourceControlLibrary`
asset before attaching a `SurveyReport` to it — the "find or create, then
link" pattern is already proven in this codebase, just needs a safe
`create_notification_type()` to call into.

Detection and delivery stay exactly as built (RE's own scheduler +
findings/metrics comparison + RFA) — Egeria becomes the catalog of record
for *what's subscribed to what*, matching the split the original plan
proposed (`docs/discovery-automate-project-context-plan.md` Part 4), not a
replacement for the detection/delivery mechanism itself.
