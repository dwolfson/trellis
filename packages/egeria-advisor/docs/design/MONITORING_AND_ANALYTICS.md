# Monitoring and analytics

**Status:** consolidated design. Current as of 2026-09-03.
**Scope:** what is measured about a query, where it is stored, and what the
measurements are for. For how queries are classified in the first place, see
`QUERY_HANDLING_AND_QUALITY.md`.

> **This document consolidates three** notes from `design/`: the monitoring
> implementation status, the monitoring next-steps guide, and the dataset/
> collection tracking analysis.
>
> **§4 is the part to read first.** Two of the three were a status/next-steps
> pair from one implementation push, and their checklists disagree with the code.

---

## 1. Why measure per collection, not just per query

A query's latency and a thumbs-down tell you *that* an answer was poor. Neither
tells you *why*, and the commonest cause is retrieval reaching the wrong
collection — which produces an answer that is fluent, sourced, and about
something adjacent.

So the design's unit is the **(query, collection) pair**: which collections were
consulted, what each contributed, and what the score distribution looked like.
That is what makes a routing regression attributable rather than merely visible.

## 2. What is stored, and where

Three destinations, with different durability:

| Store | Holds | Always on? |
|---|---|---|
| **Postgres** (`ConsolidatedDBManager`) | `query_metrics`, `system_metrics`, `collection_health`, `error_log`, `plan_events`, `ingest_log` | yes — self-provisioning on first connect |
| **MLflow** | per-query, per-collection retrieval metrics; experiment comparison | configurable (`observability.mlflow.enabled`, default `true`) |
| **FeedbackCollector** | thumbs up/down | yes |

Postgres and the vectors share the same `egeria_advisor` database, so a metrics
query and a retrieval hit the same instance.

MLflow logging runs on a **background daemon thread after `query()` returns**, so
it never adds latency to a response. That is the constraint that shaped it: a
measurement layer that slows the thing it measures gets turned off.

## 3. Query classification as the measurement key

Classification (8 types, 13 domain topics, confidence-scored) exists for routing,
but it is equally the *key* the metrics are grouped by. Without it, "queries were
slower this week" cannot be decomposed; with it, "CONCEPT queries got slower and
CODE queries did not" points at a collection.

`advisor/query_classifier.py` is live, with six importers across CLI integration,
interactive response, MLflow tracking, collection metrics, assembly metrics and
the pyegeria agent.

---

## 4. Checked against the code, 2026-09-03

### 4a. Two "completed" next steps did not happen in the files they name

`MONITORING_NEXT_STEPS` lists four items, all marked ✅:

| # | Item | Actual |
|---|---|---|
| 1 | add monitoring calls to `advisor/rag_retrieval.py` | **0 monitoring references in that file** |
| 2 | update `advisor/collection_router.py` to use query classification | **0 classification references in that file** |
| 3 | create `tests/test_monitoring.py` | exists, 394 lines ✓ |
| 4 | create `scripts/capture_baseline_metrics.py` | exists, 200 lines ✓ |

**Both are integrated — elsewhere, and differently.** Monitoring is called from
`rag_system.py`, not `rag_retrieval.py`. And the router does not import the
classifier at all: `route_query()` takes `intent: Optional[str]` and receives the
classification from its caller.

The second is arguably the better design — the router stays free of a dependency
on the classifier — but it is not what the checklist says, and a reader following
that checklist would go looking in two files that contain none of it.

**A ✅ against a filename is a claim about where code lives, and this pair is
wrong about both.**

### 4b. Per-collection retrieval metrics are durable only if MLflow is running

Two different collection-level things exist, and they are easy to conflate:

- **`collection_health`** — written to Postgres by
  `metrics_collector.record_collection_health()`, called from `rag_system.py`.
  Durable unconditionally.
- **`CollectionRetrievalMetrics`** (`advisor/collection_metrics.py`) — the
  per-query, per-collection retrieval detail that this design exists for. Its
  **only consumer is `mlflow_tracking.py`.**

So the headline measurement — which collection contributed what, for this query —
persists only when MLflow is reachable. It defaults to enabled, but it is an
optional external service on `localhost:5025`, and when it is down the logging
thread fails quietly by design.

That is a defensible trade for experiment tracking and a poor one for the
routing-regression question in §1, which needs history rather than a live
dashboard.

### 4c. The dataset-tracking analysis is six months old

`DATASET_TRACKING_AND_ANALYTICS_ENHANCEMENT` is dated 2026-03-07 and marked
"Analysis and Recommendations". Its per-collection framing is the origin of §1 and
is still right. Its specific recommendations were not re-verified line by line
here — treat the analysis as sound and the task list as unchecked.

---

## 5. Settled — do not reopen without re-measuring

| Question | Settled | On what basis |
|---|---|---|
| Is per-query measurement enough? | **No** | It shows that an answer was poor, not that retrieval reached the wrong collection |
| Should MLflow logging be synchronous? | **No** | Background daemon thread after `query()` returns; a measurement layer that slows the response gets disabled |
| Should the router import the classifier? | **No** — it takes `intent` | Classification happens upstream and is passed in, keeping the router free of the dependency |
| Are the four monitoring next-steps complete? | **Two of four** — see §4a | Tests and the baseline script exist; the two integration items are real but in different files than named |
| Are per-collection retrieval metrics durable? | **No** — MLflow only | `collection_metrics.py` has one consumer; `collection_health` is the part that reaches Postgres |
