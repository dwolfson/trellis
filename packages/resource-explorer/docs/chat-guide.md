# Resource Explorer — Chat Guide

**Status:** live. Covers the chat panel in the web UI, `resource-explorer chat` / `ask` in the CLI, and the A2A
agents.

**Last revised:** 2026-10-18

**Verification:** the example questions and a few behaviours below are marked **[V1]**, **[V2]** and so on.
They were written from the code and the intent classifier, not from a run against a live model, and are listed in
section 11 with the test each needs. Remove a marker when its test has passed.

The chat answers questions about the repositories, databases and file systems you have surveyed. It is useful
because it can say *how* it knows something and, as importantly, what it does **not** know. This guide covers
what to ask, how to read the answers, and where the limits are.

For the web UI as a whole see [user-guide.md](user-guide.md). For how answers are built internally see
[question-answering-and-context.md](question-answering-and-context.md).

---

## 1. What the chat is

- **It answers from what Resource Explorer has stored**: survey results, code symbols, dependency lists, commit
  and release statistics, indexed documentation, and RFAs. It does not look at a live database or repository
  when you ask. If a survey is old, so is the answer; ask "when was X last surveyed?" to check.
- **Numbers and lists come from tools, not from the model's memory.** The model calls a lookup, then explains the
  result. If a lookup returns nothing, the answer should say so rather than guess.
- **It is read-only**, with one exception: it can *propose* a Request For Action (section 7), and files it only
  after you agree.

## 2. Asking a question

Type in the chat panel (**Enter** sends, **Shift+Enter** adds a line). The panel is scoped to the resource
selected in the sidebar; with none selected it considers every resource.

- **Name the resource** in the question ("how many tables does adventureworks have?"). Names are matched against
  your registered slugs and display names.
- **If the name is ambiguous or missing, you get chips.** A comparison or integration question that names fewer
  than two resources shows ranked candidates you can click. Candidates you already named are left out.
- **The small badge under the box shows the intent** the question was classified as (statistical, comparison,
  integration and so on). It is a label and it picks a few special displays, such as charts. It does not stop
  other tools from being used, so a question labelled "general" can still call every tool below.
- **Evidence** (button next to Send) shows what evidence *would* answer the question and what is missing, without
  asking the model anything. It does record that a compile happened (an activity row), so it is not
  free of side effects. **[V3]** Use it when an answer looks thin.

## 3. What you can ask

Phrasings are examples; you do not need these exact words. **[V1]** Every example question in the tables below
is untested against a live model.

### One repository

| You want | Example |
|---|---|
| Activity and size | "How many commits did egeria get in the last 90 days?" · "Who are the top committers?" · "Show weekly commit activity" |
| Release rhythm | "How often does egeria release?" (latest release and average interval, when recorded) |
| Health | "Is egeria actively maintained?" · "What is the bus factor?" |
| Code structure | "How many classes does it have?" · "Signature of `CodeParser.parse`" |
| Code meaning | "How is authentication implemented?" · "Show me the code for the retry logic" |
| Concepts and docs | "What is egeria?" · "How do I configure it?" |
| Examples | "Write a Python example that lists assets" |
| Dependencies | "What does it depend on?" · "Show runtime dependencies" |

### One database

| You want | Example |
|---|---|
| Structure | "What schemas does adventureworks have?" · "Describe the `sales.salesorderheader` table" |
| Change | "What changed in the adventureworks schema since the last survey?" (needs two surveys) |
| Documentation gaps | "Which tables in adventureworks have no description?" |

### Several resources at once

| You want | Example |
|---|---|
| Comparison | "Compare egeria and openmetadata" · "Compare the adventureworks and coco_pharma schemas" |
| Integration | "Can marquez work with openlineage?" |
| Which repo uses which database | "Which databases does egeria-trellis use?" |
| Who uses a package | "Which repos use `requests`?" (exact package name; ask for "anything containing" to widen it) |
| Dependency change | "Which dependencies changed in egeria since the last ingest?" |
| Biggest or most | "Which databases have the most tables?" · "Rank databases by undocumented tables" |

### Governance and coverage

| You want | Example |
|---|---|
| A gap across everything | "Which repos have no license classification?" · "Which repos have never been scanned for CVEs?" |
| Survey history | "When was adventureworks last surveyed?" · "What analyses have run?" |
| RFAs | "What RFAs are open for egeria?" (reading only; see section 7). Add "including closed" to see completed ones **[V4]** |

## 4. Reading an answer

Every answer should keep these four situations apart. If one answer blurs them, treat it as a defect and report
it (press **f** for feedback).

| What the answer says | What it means |
|---|---|
| A number or list | **Measured** by a stored analysis. |
| "None found" | The analysis **ran** and found nothing. |
| "Not run" / "never surveyed" | **Unknown.** No one looked. This is not a pass. |
| "Not established" | An analysis exists but could not decide (for example, no readable data). |

Other things to watch for:

- **Partial coverage.** "Which repos have no license classification?" names the repos that were checked, the ones
  that were not, and, if the 30-second sweep budget ran out, the ones it did not reach.
- **Account reach.** A database survey sees only what the surveying login could read. Tables seen only through
  the catalog are reported separately: "description was not read" is unknown, not undocumented.
- **Estimates.** Row counts from the catalog are estimates and are labelled so.

## 5. Cross-resource answers: what a "link" means

"Which database does this repo use?" is answered by comparing table names in the database with class names in
the code, plus database drivers, ORM libraries and name hints. That is **evidence of shared names, not proof of
ownership.**

- By default only **high**-confidence links are listed (best first, at most 15), with a count of the medium and
  low ones. Ask for "include medium and low" to see more. **[V2]**
- High needs at least two table names that are distinctive to that database. Generic tables (`users`, `config`,
  `orders`) and tables that appear in three or more databases count for very little.
- Known weakness: a very large repository whose model classes cover many ordinary names can still reach high on
  a database that is not its own. Treat a surprising link as a question, and check it against the evidence lines.
- Two products that share a data model (for example OpenLineage and Marquez) can show as linked. That is
  "related", not "owns".

## 6. Compare and integrate

Comparison and integration questions are answered by a specialist that first compiles one body of evidence across
**all** the resources you named, then answers from it. The evidence lists what was measured for each resource and
names the gaps per resource, so "no stored result for B" is never read as "nothing found for B".

An integration answer rests on documentation, shared contributors and cross-asset links. It is **not** a
compatibility test: it does not resolve dependency versions or run anything. Treat "yes, they work together" as
"here is what the documents and metadata say".

## 7. Requests For Action from chat

When the chat finds a concrete gap (a schema mismatch, missing documentation) it may propose an RFA.

1. It shows you the proposed title and detail and says **NOT FILED YET**.
2. Only if you agree does it file it, as a local RFA on the resource.
3. It will not file a duplicate of an open RFA with the same title, will not file against a resource that is not
   registered, and caps the title at 200 characters and the detail at 4,000.

Changing an RFA later (defer, reassign, complete) is done in the **RFA drawer**, not in chat. The drawer checks
that you have write access in Egeria and keeps any linked To Do in step. The A2A agents cannot file RFAs at all.

## 8. What the chat will not do

- **Lineage.** The chat does not answer lineage questions. Use the Egeria portal.
- **Live queries.** It never runs SQL against your database or calls a repository host for you.
- **Anything it has no stored evidence for.** Run the missing analysis, then ask again. The Evidence button tells
  you which one.
- **Write to Egeria.** Publishing, curating and re-surveying are done from the main panels.

## 9. CLI and A2A

```bash
resource-explorer chat                 # interactive, multi-turn
resource-explorer ask "how many commits did egeria get in 90 days?"   # one-shot
```

The A2A agents (see [a2a.md](a2a.md)) answer the same kinds of question for other agents. When a comparison or
integration question names too few resources, the reply asks for more and includes a `resource_choices` data part
listing ranked candidates. They are read-only.

## 10. Troubleshooting

| Symptom | Likely cause |
|---|---|
| "No data" for a repo | It was never refreshed or surveyed. Run a survey, then ask again. |
| Old numbers | The stored survey is old. Ask when it was last surveyed. |
| "Not run" for a database figure | The analysis was never run for that database, or the surveying login could not read it. |
| A comparison asks "which projects?" | Fewer than two resources were recognised. Click a chip or use the slug. |
| A cross-asset link looks wrong | See section 5; check the evidence lines and report it with **f**. |
| A sweep says it stopped early | The 30-second budget ran out; the answer lists what it did not reach. Narrow it ("only repos") **[V5]**. |
| The answer ignores a document you expect | The documentation may not be indexed. Check the **chunk count** of the latest ingestion. A repository added through scouting is not indexed for chat until someone indexes it: it shows 0 chunks and no collections, and nothing about it is searchable. Counts include any shared collection (for example the Egeria web documentation), so do not add them up across repositories. **[V6]** |

## 11. Claims awaiting verification

Each needs a test run against a real registry and a live model, by the coordinator, before its marker is removed.

| Marker | Claim | How to verify |
|---|---|---|
| V1 | Each example question in section 3 is answered by the named kind of lookup, and the answer reads as described. | Ask each one on the laz data set; record the tool it called and whether the answer matches the stored data. |
| V2 | Asking for "include medium and low" makes the chat list more than the high-confidence links. | Ask "which databases does egeria-trellis use, include medium and low links"; the tool call must carry a lower `min_confidence`. |
| V3 | Evidence shows the coverage without calling the model. Checked in code (2026-10-18): `POST /api/context/compile` calls no model, but it writes a compile record. Remaining: click it with the model server stopped. | Confirm it still returns. |
| V4 | "Including closed" shows completed RFAs. | Ask for RFAs on a resource with a completed one; compare with the drawer. |
| V5 | "Only repos" narrows a coverage sweep to repositories. | Ask a sweep question both ways; the tool call must carry `resource_type`. |
| V6 | An un-indexed document is the usual cause of a missing document. Checked on laz (2026-10-18): 42 repos (34 with a 0-chunk ingestion row, 8 with none) have no collections and were never first-indexed; the bulk and scouting paths do not index. Counts are correct per repo and include the shared web-docs collection. | Re-check after that is understood. |
