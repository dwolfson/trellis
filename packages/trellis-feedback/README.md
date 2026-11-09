# trellis-feedback

One feedback store and one triage workflow, shared by Resource Explorer and Egeria Advisor.
It holds ratings of chat answers and page-level product reports. Admins set their status through
an append-only log of triage events.

Design and the project owner's decisions: [`docs/trellis-feedback-extraction.md`](../../docs/trellis-feedback-extraction.md).
This is 0.1, the library only. Neither app uses it yet: RE adopts it next, then EA (§6 of that doc).

## Why this package exists

Both apps grew feedback separately and both have gaps (§1 of the design doc):

| | Egeria Advisor | Resource Explorer |
|---|---|---|
| Answer ratings | full records, in JSONL files | effectively unrecorded (a hash-only metrics row) |
| Triage | five statuses, keyed by position in a file (which can drift onto the wrong record) | three statuses on page feedback, with no UI to set them |
| Who can read and triage | any signed-in user | admins |

## What it does

- **Items** (`FeedbackItem`) have a `kind`: `answer` (vote, question, full answer text, intent
  label, compile id, resource scope) or `product` (category, page, message, rating, contact
  consent). Each has a stable id assigned by the store, and a submit can carry an **idempotency
  key**, so a retry is not a duplicate.
- **Triage is append-only.** Each status change is a `TriageEvent`, ordered by a monotonic
  sequence id. An item's status is its latest event's, or `new` if it has none. Notes live only
  on events, so nothing is ever overwritten. Statuses: `new`, `triaged`, `known_issue`,
  `actioned`, `deferred`, `not_an_issue`.
- **External rows** (RE's Curate `resource_feedback`) are triaged by reference,
  `(app, source, id)`. The source must be on a list the app declares. When the app deletes such
  a row itself, its history stays and is reported as "gone" until an admin clears it.
- **Deleting an item deletes its triage history too**, in one transaction.
- **Storage:** Postgres, with the tables in a schema of the app's choosing, or SQLite. The tables
  are `trellis_feedback_items` and `trellis_feedback_events`.

## Usage

```python
from trellis_feedback import FeedbackItem, FeedbackStore

store = FeedbackStore(
    "postgresql://egeria_advisor:advisor@localhost:5442/egeria_advisor",
    app="resource-explorer",
    schema="resource_explorer",
    external_sources=("resource_feedback",),
)

item, created = store.submit(
    FeedbackItem(app="resource-explorer", kind="answer", vote=-1,
                 query_text="what changed?", response_text="...", user_id="peterprofile"),
    idempotency_key="client-generated-uuid",
)
store.triage(item.id, "triaged", note="looking at it", actor="erinoverview")
store.list(status="triaged")              # each row carries its current "triage" state
store.triage("42", "known_issue", source="resource_feedback")
store.delete_item(item.id)                # removes its events too
```

### Routes (`api` extra)

```python
from trellis_feedback.router import make_router

app.include_router(
    make_router(
        store,
        is_admin=lambda request: ...,      # the app's own admin check
        current_user=lambda request: ...,  # the signed-in user's id, or ""
        external_lookup={"resource_feedback": lambda ids: ids_that_still_exist(ids)},
    ),
    prefix="/api/feedback/v2",
)
```

| Route | Who |
|---|---|
| `GET /meta` | anyone the app lets through |
| `POST /items` | anyone the app lets through; the user comes from `current_user`, never from the body |
| `GET /items`, `GET /items/{id}` | admin |
| `POST /triage` | admin |
| `DELETE /items/{id}` | admin |
| `GET /external/{source}?ids=…` (states, plus gone rows) | admin |
| `DELETE /external/{source}/{id}` (only once the row is gone) | admin |

The library reads no environment and decides nothing about identity: the app passes in its URL,
schema, admin check and current user.

## Tests

```bash
uv run --package trellis-feedback pytest packages/trellis-feedback/tests
# and on Postgres too, in a throwaway schema that is dropped afterwards:
TRELLIS_FEEDBACK_TEST_PG_URL=postgresql://egeria_advisor:advisor@localhost:5442/egeria_advisor \
  uv run --package trellis-feedback pytest packages/trellis-feedback/tests
```
