# Resource Explorer — User Guide

**Status:** live. Investigations, work lists, private work, the questions, Curate, Publish, Files and live status are current.

**Last revised:** 2026-10-28 (the date of the commit that last changed this guide)

Resource Explorer (RE) discovers, surveys, and catalogs information resources using Egeria as the metadata catalog. This guide is organized by what you are trying to do. Each section opens with the words the screen uses and ends with what is not built yet, with a date.

**How far to trust the screen words.** A sentence marked "(not re-verified on <date>)" is one the writer could not open on the running app that day. On 2026-10-28 the app on port 8813 asked for sign-in while this guide was written, so the writer could not open any screen that day: the screen words quoted below are those the audit of the same day read while signed in (`design-notes/AUDIT-USER-GUIDE-2026-10-28.md`), and every section that quotes them ends with the line "(screen words not re-verified on 2026-10-28)".

1. [Start here](#1-start-here)
2. [The words and marks](#2-the-words-and-marks)
3. [Investigations, scope and work lists](#3-investigations-scope-and-work-lists)
4. [A resource, stage by stage](#4-a-resource-stage-by-stage)
5. [Repositories, databases and file systems](#5-repositories-databases-and-file-systems)
6. [Publishing to Egeria](#6-publishing-to-egeria)
7. [Extending and customizing](#7-extending-and-customizing)
8. [Admin](#8-admin)
9. [The CLI](#9-the-cli)
10. [Not built yet](#10-not-built-yet)

---

## 1. Start here

### Starting the web UI

```bash
uv run resource-explorer web     # → http://localhost:8810
```

The app is served at `/`. The browser tab's title still carries the name of an older route; that is a known defect, and the address is `/`.

### Signing in

Resource Explorer asks you to sign in before it shows anything. The sign-in panel reads "Sign in with your Egeria user id to continue." Use your **Egeria user id and password**: Egeria is the identity provider, and there is no separate Resource Explorer account.

Your password is used once, to get an Egeria token, and is never stored. From then on every read and write RE makes runs *as you*: Egeria's own provenance records your user id, and anything you publish is owned by you.

**Sessions last about an hour**, because that is how long Egeria's tokens last, and they all end when the Egeria platform restarts. When yours lapses the sign-in panel reappears; sign in again and carry on. Opening Resource Explorer from inside the Egeria Portal skips this entirely: the Portal hands over the token it already holds.

The header shows who you are signed in as, and **Sign out** ends the session. One known defect: with no investigation selected, the header's connection-details control can read "not signed in" even though you are signed in; with an investigation selected it reads your user id. It is on the defects queue, and the sign-in itself is not affected.

### The screen

- **Stage strip** along the top. It reads **Investigation · 1 Scouting · 2 Discovery · 3 Assessment · 4 Analysis · 5 Enrichment · 6 Curate · Understanding · Automate · ▦ Work lists**. The run goes left to right through the six numbered stages. **Investigation** (the frame) sits before them, and **Understanding** and **Automate** are cross-cutting.
- **Left sidebar**: resources grouped by kind (repositories, databases, file systems), then the current investigation with **Scope · N** and **Work lists for <name> · N**, then **Other work lists · N**. A **PERSPECTIVE · 0 OF 12** filter narrows the list by who is asking.
- **Main panel**: the selected stage for the selected resource. A stage opens sub-tabs: **Questions · Survey & analyses · By analysis · Disposition**.
- **Header**: who you are signed in as, **📋 Activity** and **⚙ Admin**. The **RFAs** drawer is in the strip (**RFAs 57** is an example count).
- **Chat rail**: on every stage. It reads "ASK · scoped to <resource> · what would answer this?"

### The three jobs

1. **Find and judge a resource**: the six stages, section 4.
2. **Catalog it into Egeria**: Curate and Publish, section 6.
3. **Extend the Explorer**: add an analysis, a question, a purpose or a setting without touching RE's code, section 7.

### Who can see your work, and what "owned by you" means

Everything you publish to Egeria is written **as you**. Egeria's own record shows your user id, and the elements you create are owned by you. A run that a person starts in the Explorer, or that a schedule starts later, publishes in the same way, with the same care about whose work it is (see "Private investigations").

**Resource Explorer adds no zone of its own.** Egeria "zones" are the labels a deployment uses to say who may see or change an element. By default RE sends none, so what you publish follows the deployment's normal rules. The Curate band on a resource reads "zones: none · everyone visible". A draft is a *content status* (a draft is something a person has not yet accepted), not a zone. The older "draft zone" (`resource-explorer-draft`) was retired on 2026-10-08. A deployment can still choose to configure one; ask whoever runs your Explorer (the admin guide, "Governance zones", says how).

- **Egeria's zones decide who may curate.** Where no governance zone is in use, any signed-in person may accept, reject or publish. Where zones are in use, you may change an element only if Egeria's zone security would let you update it; a Portal curator or admin role may always. A refused row says "not permitted" and why.
- **Accepting is a decision, not a write.** Accepting or rejecting a finding records your decision in RE. Nothing reaches Egeria until someone presses **Publish** (see section 6).

### Live status

Things you start keep reporting back without you reloading:

- **Activity badge.** The Activity link in the header shows **N new** when entries are newer than the last one you looked at (for example "📋 Activity 200+ 9+ new"). It checks every 30 seconds. The first time on a browser nothing is flagged, so it does not open with a large count.
- **Toast.** When a run or batch finishes (or fails) while you are elsewhere, a small notice appears with the summary and a **View** button that opens the entry. It closes itself after a few seconds.
- **Imports and runs.** A batch import follows its own rows and updates the sidebar as each repository lands. A question whose analysis is running shows ◔ *running* and fills in when the result is stored.
- **Banners.** If the server or its database stops answering, a banner says so in a few words ("Server not responding", "Database unreachable"). If your session lapses a single **Signed out** banner with a **Sign in** button replaces the errors each pane would otherwise show.

Every status word comes from rows RE stored, not from the fact that a button was pressed.

### The Activity log

The **📋 Activity** link in the header opens the persistent activity log. Every operation writes an entry (scout, survey, catalog, publish, rfa, refresh), and each entry shows its status, a summary, and expandable annotation details. (entry kinds not re-verified on 2026-10-28)

### Tips

- **Column widths are resizable.** Drag the thin divider between the sidebar and main content, or between the main content and the chat rail or RFA drawer. Your chosen widths are remembered across reloads.
- **The feedback button** (bottom-right, 💬 Feedback) is draggable if it is ever in your way; its new position is remembered.
- **Keyboard:** `Enter` submits a chat message; `Esc` clears the chat input.

**Not built yet in this section:** nothing; see section 10 for the whole list.

(screen words not re-verified on 2026-10-28)

---

## 2. The words and marks

RE shows a state as a **mark plus a short word** on the thing itself. Hover (or open the details) for the full sentence.

### The marks

| Mark | Reads as | Means |
|---|---|---|
| ✓ | answered, measured, published | It was done and checked. |
| ✓ | answered automatically | Appears as a distinct key beside "answered". |
| ∅ | nothing found, empty | It was measured and there was nothing. This is an answer, not a gap. |
| ◐ | partial, structure only, within credential scope | Measured, but only part of the picture. |
| ○ | not run | Nobody has run it yet. |
| ◌ | no reader yet, undecided | There is no answer to give here yet. |
| ? | not established, could not read | RE could not tell. Not the same as "no". |
| ⚠ | needs you | A person has to act. |
| ◔ | running, queued | Under way. |
| ✕ | error, failed | It failed; the word says why. |
| □ | stored, archived | Results exist but have not been read, or it was archived. |

### The chips on Curate

A database's Curate page, under "What gets published", shows three chips. A chip reads either ✓ or ◌ with the cue **not checked since <time>**. For example a chip can read "cataloged by Egeria 0 schemas ◌ not checked since 00:54". A chip is a statement about the last time RE read Egeria, not about Egeria now.

### The absence words

An empty box could mean four different things, and RE keeps them apart:

| The screen says | It means |
|---|---|
| **not measured** | Nobody has measured it. Not the same as zero. |
| **nothing found** | It was measured and there was nothing. An answer. |
| **could not read** | RE tried and could not (the source did not answer, or the account cannot see it). |
| **not permitted** | The account or the zone does not allow it; the row says why. |
| **not applicable** | The question does not apply to this kind of resource. |
| **planned, not built yet** | The result kind exists in the design and no renderer draws it yet. |

Two more you will meet: **not yet surveyed** (a repository registered but not scouted, never zero) and **measured within what this account can see** (a database answer from an account that sees only part of it).

### "as of"

A number that comes from a source that changes carries the time it was read: "as of 10-19". Numbers taken from a database's own statistics are estimates as of the last time the database refreshed them. Read a figure together with its "as of".

### Confidence badges

A proposal, such as a component in Architecture Recovery, carries a **confidence** from 0 to 100. It reflects how directly the evidence establishes the claim, not how important the thing is.

### Where it lives: "local · not published" and "published as <you>"

- **local · not published**: RE holds it and Egeria does not. A choice you made and an unpublished survey read this way.
- **published as <you>**: Egeria has it, written under your user id. Someone else's rating or note reads "<person>'s · waiting for them".

### Decisions in Curate

In Curate, a choice is **Include** or **Leave out** and is saved in RE the moment you press it. A row that is left out, or **deleted in Egeria**, is shown lowered in muted ink; "deleted in Egeria" has no mark of its own, only the word. "Saved · will publish" means RE holds your change and Egeria does not yet; "published 10-11" means Egeria has it. A draft finding is one nobody has accepted yet.

### Defects seen on 2026-10-28

Six things on the screen are wrong today, and are not intended behavior: a database header can read "never surveyed · not published to Egeria" while the Curate band says it is published; the same band can give two counts for one fact (schemas attached, schemas cataloged); the connection-details control reads "not signed in" while you are signed in; some panes (Discovery, Enrichment, Analysis) stay on "loading…" for several seconds without saying what they wait for; an unknown stage name in the address (for example `?stage=admin`) leaves the main panel blank; and the browser tab's title still carries an older route's name. They are queued for fixing, not documented as design.

**Not built yet in this section:** nothing in the vocabulary; see section 10.

(screen words not re-verified on 2026-10-28)

---

## 3. Investigations, scope and work lists

### What an investigation is

An **investigation** says *why* you are looking at a set of resources. It has a name, a description, a kind (for example Personal, Experiment, Task, Campaign or Study) and one or more **purposes**. Its **scope** is the set of resources it covers, and the scope can mix repositories, databases and file systems.

The **Investigation** stage, at the left of the stage strip, is where you start one and see its scope. It lists purposes, status, scope count, and where each investigation lives: **☁ Egeria**, **🏠 local**, or **unbound by reset**. "Unbound by reset" is the word shown for an investigation that was bound to Egeria before the 2026-10-23 reset and is not bound now.

Once an investigation is *current*, the sidebar shows **Scope · N** and **Work lists for <name> · N** under it, and a resource that is in the scope says so ("already in <name>'s scope"); otherwise the act reads "add to <name>".

An investigation is a way of framing your work. The investigation says what a piece of work is for.

### Purposes

Pick a purpose from the list when you start an investigation (or when you fill in Enrichment's **Intended use**). The list is kept in Egeria as a valid-value list, so everyone using the same Egeria sees the same choices. It is **suggestive, not strict**:

- You may type a purpose that is not in the list. It is kept exactly as you wrote it, and it shows a small "◌ not in the list" cue instead of an error.
- If Egeria cannot be read, RE shows the last list it read and says how old that copy is; with no copy at all, it shows the list that shipped with it, and says so.

Purposes order the questions: a stage's Questions tab reads, for example, "ordered by purpose · Explore, Learn · 4 of 6 lead", and a question that is not among the current investigation's purposes is marked "NOT AMONG THIS INVESTIGATION'S PURPOSES".

### Private investigations

An investigation of kind **Personal** or **Experiment** is **private to its owner**: you.

- In RE, nobody else sees it in their list. It carries a 🔒 mark.
- In Egeria, what it produces (its survey reports and their findings) is written with the zones `[resource-explorer-private, <your user id>]`, so Egeria's own security lets only you read it.
- **The work runs as you.** Only the signed-in owner can write a private investigation's reports. If a schedule or another person's session reaches one, RE does not write it; the row waits, reading "waits for <owner> to publish", and your next Publish sends it.
- The repositories, databases and file systems in a private investigation's scope are shared things. RE does not hide them from other people; only what the investigation *produces* is private.
- Today a private investigation can publish **repositories**. Databases and file systems in a private investigation are refused with a clear message instead of being published where others could read them.
- Changing a private investigation to a public kind always works. Changing a public one to a private kind can stop part-way if something already reached a public zone; the result lists exactly what moved and what did not.

An older private investigation created before RE recorded owners shows a note saying so, and is visible to everyone until it is recreated.

### Work lists versus investigations

Three words, three jobs:

| Word | What it is |
|---|---|
| **Investigation** | *Why.* Purposes, description, verdicts. |
| **Scope** | *Which resources*, of any kind, that the investigation covers. |
| **Work list** | A *bench*: one kind of resource laid out as rows against one stage's questions, so you can decide which ones belong in a scope. The strip's control reads "Compare a set of resources as rows x questions". |

To use one: choose **Select several…** in the sidebar, tick some resources of one kind, and press **save as work list…**. Open the list from **▦ Work lists** in the stage strip (it shows how many, for example "▦ Work lists 6"). From there you can run one survey across the whole list, compare the results, narrow the list to a shortlist (**promote**), and then **Add to an investigation…** or **Start an investigation from this list…**. Publishing a work list is explicit: creating one writes only to RE.

Lists that start with `suggested-to-` are not work lists. They are inboxes for entries other people pointed you at from the journal ("suggest to…"), and they have their own **Suggestions** line in the sidebar.

### Saving a chat answer to the journal

With an investigation chosen, an answer's footer has **add to investigation journal**. Since #841 the entry is derived from the chat turn, not an editable entry seeded with a citation; it joins that investigation's journal, shown at the foot of the investigation page. Entries stay in RE until the investigation is promoted to Egeria. Once it is, **Publish my entries** on the investigation page sends your own entries to the Project as Notes in its note log; each entry shows its state. A person publishes only their own.

**Not built yet in this section:** the winnowing columns on a work list, and mixed-kind lists; see section 10.

(screen words not re-verified on 2026-10-28)

---

## 4. A resource, stage by stage

Every analysis in the catalog is tagged with one of **eight intents**: Scouting, Discovery, Assessment, Analysis, Enrichment, Understanding, Curate, Automate. The tags come from `resource_explorer/configdata/analysis_catalog.yaml`. On the screen the intents are the stages of the strip. Automate has no analyses of its own: it holds schedules and subscriptions.

### The questions behind each stage

Resource Explorer organizes its checks as a **question catalog**. Each question has an id (**Q-0001** upward; the newest today is Q-0109), a funnel stage, the resource kinds it applies to, and the way it is answered. A stage's **Questions** tab lists the questions for the selected resource, grouped by purpose.

- **The id never changes; the text may.** Seven questions were reworded on 2026-10-22: the id is stable, the text changed. Retired and merged questions keep their ids and stay in the catalog, dimmed, because past answers refer to them.
- Answers you give in Enrichment are saved with the id of the question they answer.
- Administrators browse the catalog under **Admin → Question Catalog**. The source is `docs/dr-egeria/resource_questions.csv`, explained in [`dr-egeria/resource_questions_guide.md`](dr-egeria/resource_questions_guide.md).

A stage opens sub-tabs: **Questions** (each question has its own **run**), **Survey & analyses** (the definition's **Survey** press), **By analysis** and **Disposition**.

### Scouting
*Goal: broad inventory across many resources, fast*

Scouting is the Questions tab of stage 1 for a repository, plus the **Survey & analyses** tab, where a definition's **Survey** press runs the scouting analyses:

- Language and file classification
- Repository health metrics
- Basic dependency detection

Results appear in the Activity log.

**The header tiles.** A repository's header shows the numbers a first look needs: **WEBSITE**, **LANGUAGE** ("python measured" when the language was measured), **STARS**, **SECURITY** (reads "? not read" until the security step has run), **DEPLOYMENTS**, and **SCOUTING SIGNAL**. A tile that has not been read says so: SECURITY reads "? not read", not zero.

**Importing many repositories.** Use **＋ Find repos** ("Find and import candidate repos") at the bottom of the repositories sidebar. It has two ways in: a **search** (keywords, stars, language, license, organization, topic) and **From a list** (a CSV with an `address` column, or one GitHub URL per line; an organization URL expands to its repositories). Either one only fills a review table. **Nothing is registered until you tick rows and press Import Selected.**

- **Progress comes from the press.** The button reads *Importing…* and each row shows its own state (importing, imported, failed) as the repositories finish. The sidebar fills in as they land, and the batch also appears in the Activity log. You can close the dialog; the import carries on.
- **Already-registered repositories are skipped**, and the status line says how many. A repository that another batch is importing at that moment is left alone and counted separately.
- **Statistics are deferred.** Import registers a repository at once and does not fetch its GitHub statistics. Until the first scouting survey runs it reads **not yet surveyed**, never zero. The survey fetches the numbers.
- You can choose a group for the whole batch, and set a disposition on a row before you import it.

**Where the docs are.** A repository's homepage and its documentation are often different places. When the Scouting survey's homepage step has run, the repository header shows the **Project site** and, beside it, the documentation link with one short cue:

| Cue | Means |
|---|---|
| **docs ✓** | A documentation site was found and it answered. |
| **docs unreachable** | One was found but did not answer when RE looked. |
| **no docs found** | RE looked in the repository and its manifests and found none. |
| **docs not checked** | A link is known but has not been checked yet. |

Nothing is drawn before the homepage step has run: "not measured" is not "no docs found".

### Discovery
*Goal: find what a resource is, from what its surveys revealed*

Discovery is a stage with its own questions. For a database there are 19 of them (for example db_cataloged, db_existing_use, db_feedback, db_surveyed, db_disposition, reach and db_classification), answered on the page. Chat is a rail on every stage, not a Discovery panel; see "Asking in the chat rail" below. The pane can take several seconds to fill on a large database, while its rows read "loading…" (a known slowness).

### Assessment
*Goal: deep analysis of a specific resource*

Assessment is a Questions tab like the others: open the Assessment stage and run a question's analysis from its row. The analyses include:

- `dependency_analysis`, the full dependency graph with version pins
- `security_scan`, secrets, vulnerable patterns, exposed credentials
- `documentation_coverage`, the doc ratio by file type
- `data_file_profiling`, column counts, row counts, null rates for CSV and Parquet files
- `api_structure`, detected API endpoints and OpenAPI specs
- `egeria_publish`, which registers the resource in Egeria and triggers its native survey

### Analysis
*Goal: structural and quantitative analysis of a specific resource, fast, not scored*

Analysis questions do not evaluate the resource against criteria; they extract and report structure. You reach them from the Analysis stage's Questions tab and from **Curate › Structure**. This is where **Architecture Recovery** lives (`architecture_recovery`). The Analysis tab can read "0 of 20 answered · 20 still loading" for a few seconds on a first open.

#### Architecture Recovery

Architecture Recovery reads a repository and proposes a **candidate component partition**: a set of components (each a path prefix within the repo), where the evidence for each one came from, and how confident the tool is. It draws on four kinds of signal: package manifests (`pyproject.toml`, `package.json`), deployment artifacts (`Dockerfile`, `docker-compose*.yml`), code markers found by scanning the source (web-framework routes, entry points, scheduler and worker decorators, and similar), and coupling between modules (who imports whom, what tends to change together).

**This is a proposal, not a published blueprint.** It is one tool's best current read of the repo's structure, with confidence and evidence attached to every claim, not an authoritative statement of what the architecture *is*. Treat a low-confidence or single-source component as a suggestion worth checking, not a fact to build on.

**Results can be partial.** You can run Architecture Recovery scoped to just one cataloged sub-resource instead of the whole repo. A scoped run only ever sees the files under that path, so its component set is incomplete *by construction*, not because the detectors missed anything. If a component count looks surprisingly small for the size of the repo, check whether the run was scoped to a subtree before concluding the rest of the repo has no structure worth finding.

**Component "shapes."** Components proposed from import and co-change coupling (as opposed to a manifest or a deployment file) are labeled with a shape that explains why the tool believes they are a real boundary:

- **cohesive**: the files in this component mostly import each other and rarely reach outside it.
- **connective-library**: internal cohesion is low, but that is because many *other* components depend on it, evenly. A shared library legitimately has almost no internal cohesion of its own; this shape is how the tool tells that apart from noise.
- **connective-orchestrator**: the mirror image: this component reaches out to many others rather than being reached into. Typical of a CLI, a web front end, or anything whose job is to coordinate the rest of the system.

**`proposed_by` tells you how a component was found**, and by how many independent approaches: `manifest`, `deployment`, `code marker`, or `coupling`. A component that shows up under two or more approaches has stronger, independently corroborated evidence than one that shows up under only one, even though the confidence number itself does not currently rise just from agreement, so read the `proposed_by` list, not only the percentage.

**Confidence** is an integer from 0 to 100, shown per component. It reflects how directly the evidence establishes the claim, not how important the component is: a Dockerfile with a declared, human-chosen container name scores higher than one inferred from a bare service key; a manifest with an explicit console entry point scores higher than a package that is merely installable; a coupling-derived shape generally scores lower than a component backed by a stated deployment or manifest artifact, because it is inferred rather than declared.

### Enrichment
*Goal: provide human context; answer open RFAs*

The **RFAs** drawer in the strip (for example "RFAs 57") lists open RequestForAction items. They are generated automatically when a survey creates a `RequestForAction` Egeria annotation, or when the Context tab has blank critical fields. Answers are saved in RE, and **RFA answers do sync to Egeria**.

The **Context** tab lets you fill in resource context proactively. Its fields are **Environment, Owner, Steward, Sensitivity, Intended use, Actual use, License, Location, Backup status, Retention, Criticality and Notes**, plus rows for documentation sources (user manual, API reference, data dictionary and others). The tab can read "Reading what's been supplied…" for several seconds before it fills.

#### The RFA drawer

Open **RFAs** in the strip. It lists open items, grouped by resource, with a count showing how many are open. Each item has response actions and a free-text answer field:

- **⏸ Defer**: pick a date to revisit it later. It drops out of the default (open-only) view until then.
- **👤 Reassign**: hand it to someone else by name or email.
- **✓ Complete**: mark it resolved, optionally with a note.
- **↺ Reopen**: bring a deferred, reassigned or completed item back to open.
- **✏ Record answer**: a free-text box for the actual answer, independent of its response-action status.

Check **Show resolved** to see deferred, reassigned and completed items alongside the open ones. (The five response actions were not re-verified on 2026-10-28; the sync of answers to Egeria is the audit's reading of the code, also not re-verified on that date.)

### Understanding
*Goal: see a resource over time*

Understanding has three tabs: **At a glance** (tiles, and **Since the last run**, which reports what changed between the last two surveys: file counts for a repository; schema, table and column differences for a database), **Contents**, and **Over time**. There is no Artifacts tab yet.

### Automate
*Goal: make a run repeat, and be told when its answer changes*

Automate has three tabs: **🔔 Subscriptions**, **⏱ Schedules** and **First indexing**. You create a subscription from **🔔 notify me** on a question row. A row can read "● active — but never fires (no schedule)": the subscription exists and nothing will ever re-run the analysis, because no schedule is set. Add one under **⏱ Schedules**. When a scheduled re-run produces a materially different result, an RFA shows up in the drawer.

### Curate
*Goal: decide what is published to Egeria, and make a resource easier to find and more trustworthy to reuse*

See section 5 for the page of each kind. Deciding and sending are separate. Everything on Curate saves in RE first. Egeria changes only when you press **Publish**, and Publish lists what it is about to write.

**A repository** has **three tabs**, split by job, and opens on the first: **Describe and publish**, **Contents** (with its count line, for example "∅ 0 chosen · ◌ 22 undecided") and **Structure**.

1. **Describe and publish**: **FINDABLE** (tags, group), **WHAT PEOPLE SAY** (ratings and notes, with "suggest to"), and **PUBLISH TO EGERIA**. The one **Publish** button lives at the bottom.
2. **Contents**: choose what is published. You pick files and folders by name; each row has an **Include | Leave out** choice, saved in RE as soon as you press it. Nothing is taken wholesale.
3. **Structure**: what the resource is made of and how it relates: components, blueprints, dependencies and the rules. Accepting or rejecting a proposal here is a decision; it writes nothing to Egeria on its own.

**One Publish per page.** **Decision (project owner, 2026-10-11):** "I think there should be one publish button, but each section can have a save or indication that it will be published when the user presses publish." On a repository's first Curate tab, every section saves in RE only, and shows where it stands as a mark and a short word: **saved · will publish**, **published 10-11**, **not sent · <reason>**, or, for someone else's rating or note, **<person>'s · waiting for them**. The **Publish** band is the last thing on the tab, and one press sends:

1. the survey report;
2. the tags and the group (below);
3. documentation sources not yet in Egeria (as ExternalReferences on the asset);
4. **your own** rating and notes, written in Egeria **as you**. Never anyone else's: another person's rating and notes wait for their own Publish.

The band has three lines. Line 1 is one state: **✓ in Egeria · published 10-11 · confirmed** when Egeria's read-back after the publish shows the same report with the same number of annotations; **published 10-11 · not yet confirmed** when there is no read-back yet; **◐ published 10-11 · Egeria shows N** when the read-back differs. **Show in Egeria ▸** opens the report rows Egeria holds (GUID, annotations, Ask about this). Line 2, **next publish**, names the kept survey (and how much of it is stale) and lists what the press will send. Line 3 holds **Publish** and **Re-survey now**. A press shows **◔ publishing…** at once; if anything fails, a pop-up says what and why (with **Retry** where a retry can help), and the failed item keeps its "not sent" mark after the pop-up closes. The steps of the press are behind **details ▸**.

**Ratings and notes go to Egeria, public, under your name.** **Decision (project owner, 2026-10-11):** "It goes under the user who is logged in and entering the ratings etc. It is also possible for another user to login and evaluate the same resource and put in different feedback." / "Ratings and notes should be public too."

- **One rating per person.** Your newest rating (stars and message) is your Egeria Rating on the asset; a newer one replaces yours there, as Egeria keeps one rating per person per element. Your earlier ratings stay in RE under **earlier ratings ▸**; RE never deletes them. A comment without stars stays in RE ("kept in RE · no rating").
- **Each journal entry is one Note** in the asset's note log ("Notes on <resource>"). Notes are never edited or deleted: a correction is a later entry. Who you suggested an entry to stays in RE (it is a work-list entry, not Egeria content).
- If Egeria refuses or cannot be reached, the item reads **not sent · <reason>** (or **not permitted · <reason>**) and is sent again only by your next Publish.

**Tags and the group go to Egeria** (the Findable band). **Decision (project owner, 2026-10-10):** "tags should be public", "Use Folio", "Yes, removing a tag removes it in Egeria".

- A tag becomes a **public InformalTag** linked to the resource's asset. RE looks for a tag of that name first and uses it, so everyone's "sales" is one tag in Egeria, not one per person. A new tag keeps the capitals you typed.
- Only a person's Publish sends tags and groups; background publishes (scheduled analyses and the like) never do. If you may not make one of the changes waiting, that item reads **not permitted · <reason>** and the rest still go.
- The resource's **RE group** becomes a **Folio** named `Folio::RE::group::<group>`, with the resource as a member. Changing the group moves the membership at the next Publish; choosing "Ungrouped" removes it.
- **Removing a tag removes that tag from the resource in Egeria** at the next Publish, including the same tag added to it directly in Egeria by anyone: Egeria removes every link between the tag and the resource. The tag itself stays in Egeria, and so does a Folio when you leave or delete a group: RE never deletes either. The owner deletes those elements by hand.
- A failed removal is never sent again on its own, not even by a later Publish: press **retry** on it. Changing a tag or the group needs the same curation rights as other Curate decisions (see the admin guide, "Who may curate and publish"); so does deleting a group, which is refused as a whole, naming who, if any member may not leave its Folio.
- Group changes from the CLI (`group assign`, `group unassign`, `group remove`) and from a CSV import need you signed in and take the same check; Egeria's Folio follows at the resource's next Publish.

### Steps that run by themselves

Some questions can only be answered after an earlier step has run. For example, profiling a database's columns needs its schema inventory first. When you ask, Resource Explorer works out what is missing and handles it for you in one of two ways, and **your own choice of tier is the consent**: (not re-verified on 2026-10-28; it needs a press, and nothing here was pressed)

- **Cheap and within what you asked for: it just runs.** The row afterwards says what happened, for example *Ran postgres_schema_and_stats first, then postgres_column_profile.* If a fresh stored result already exists, nothing extra runs.
- **Costlier than what you asked for: it asks first.** The row shows *Answering this needs step → step first*, the estimated time (and whether that is measured from earlier runs or only declared), and why it is asking. Press **Run it** to go ahead, or **not now — nothing has run** to leave it.

If the account for a database can only see part of it, the choice reads **Run it anyway — and say so**; the result is then marked as measured within that account's reach, never as the whole database. **ask for broader access** raises a request to the database owner.

### Asking in the chat rail

The rail reads "ASK · scoped to <resource> · what would answer this?" The scope shown on the rail replaces the old slug prefix: you do not type the resource's name to scope a question. Since #899 the answer is compiled from the declared extents of the analyses, by question id, so an answer cites the rows of the analysis that produced it.

**Not built yet in this section:** an Artifacts tab on Understanding, and renderers for seven result kinds; see section 10.

(screen words not re-verified on 2026-10-28)

---

## 5. Repositories, databases and file systems

### Repositories

Everything in sections 3 and 4 was written for a repository first: **＋ Find repos**, the header tiles, "Where the docs are", Architecture Recovery, and Curate's three tabs. A repository's Curate "Contents" lists its files and folders; a repository's items go out with the same Publish.

### Databases

**Database access and credentials.** Resource Explorer surveys a database with **the account you give it**, and its answers are only as complete as that account can see. Two things follow.

**What to supply when you register a database.** A read-only account that can see the catalog and statistics. Table data access is not needed yet: Scouting and Discovery work from the catalog alone (structure, keys, comments, row estimates, activity), and Resource Explorer asks for a broader account only when a specific survey needs to read rows, telling you which one and why. Passwords are encrypted at rest and never shown back.

**The credential banner.** After registration Resource Explorer probes what the account can see and shows it persistently on the database, for example *"Connected as egeria_user — sees 6 of 8 schemas; can read 3 of 26 tables; no write access."* Every answer on that database then says whether it was measured completely or **measured within what this account can see**. A count of "3 tables" from an account that can read 3 of 26 is reported as "3 of 26", never as "3". (The banner itself was not on the header of the database opened in the 2026-10-28 audit; it is not re-verified on 2026-10-28.)

**When a survey needs more.** A survey that must read rows (column profiling, data-class matching, coverage checks) is not run silently with an account that cannot. Its row says what it needs and offers three choices: run only the parts the current account can answer, pick a broader account already registered for this database, or send a request to the database owner naming the exact grant. Retry appears only when retrying could change the answer.

**Estimates versus actuals.** Numbers taken from the database's own statistics are estimates as of the last time the database refreshed them, and are labeled with that date and how many rows have changed since. Exact counts come from the later, heavier surveys. See [`docs/security-model.md`](security-model.md) for the full model, including how Egeria's own surveys and Resource Explorer's local surveys choose which account to use.

**Curate for a database is one page**, not three tabs: **FINDABLE**; **What gets published**, with its three chips (see "The chips on Curate", section 2); **Your scope**, with **Depth**; and the **Include / Leave out** table of schemas and tables. The **publish table** of declared measures (#886) is on the same page: one row per measure an analysis declared, with a "writes as" column naming the Egeria annotation it will become. A database page also shows **By analysis**, which carries **curation coverage** (see "The Analytic Library", section 7). The quality-checks section was not reached on 2026-10-28 and is not re-verified on that date.

**Data quality checks.** A PostgreSQL database can be profiled and checked for quality with the **DatabaseQualitySurvey**. You review the proposed checks under **Curate → Structure → Quality checks** (Accept | Reject, and **Watch for drift** per table), and the results reach Egeria as QualityAnnotations. The checks are DataOps TestGen's test types, which Resource Explorer runs itself. The whole path, including what is still arriving, is in [testgen-integration-guide.md](testgen-integration-guide.md).

### File systems

A file system is registered with a **host** and a **container path** (remote mechanisms are not built, see section 10). The file system's **Survey & analyses** tab reads:

- **FOLDER SURVEY**, with the **reach line**, for example "✓ Egeria can read /deployments/loading-bay · led by Egeria's Folder Survey". 
- Presses: **Survey / Measure** beside **Egeria's survey**, **Publish these measures**, **Profile data files** and **Derive**.
- The **Egeria file-name CSV** disclosure.
- Counts and **FILE TYPES**.
- **WALK MEASURES**: "walked to the end of every folder", "per-file rows kept · 134 files" (the file count belongs to the example), world-readable counts, modes, and hashes (with the 10 MB limit).
- **HEAVIEST FOLDERS** and **BY DEPTH**.
- **FOLDERS THAT DESCRIBE THEMSELVES**: narratives found in a folder are shown as proposals; "confirm it on Curate".

Four steps, `fs_change_rates`, `fs_duplicates`, `fs_activity` and `fs_permissions`, run through RE's Files host and appear under **Derive**. Four database steps are Egeria-dispatched; the start-up line counts only those four (ruled 2026-10-28). A file system's root folder is published from Curate by its own Publish. (This subsection quotes the audit's reading of the screen; not re-verified on 2026-10-28.)

**Not built yet in this section:** remote reach for file systems; see section 10.

(screen words not re-verified on 2026-10-28)

---

## 6. Publishing to Egeria

Publishing is always a **person's act**: a button press by someone signed in, and the changes are written as that person. Nothing publishes itself because you accepted a finding or made a choice.

What a press can send, by where it comes from:

| From | What Egeria receives | Where you press |
|---|---|---|
| The survey you already kept | A survey report on the resource's asset, with its annotations (measurements and observations) | Curate, **Describe and publish**, bottom |
| Tags and group | Public tags and a Folio for the group | Same Publish |
| Documentation sources | External references on the asset | Same Publish |
| Your ratings and notes | Your rating and your notes on the asset, under your name | Same Publish |
| Files, folders, schemas and tables you included | Each becomes its own asset related to the resource | Chosen on **Contents**; a repository's items go with the same Publish, a database has its own commit panel on that tab |

Three things to know:

- **No zone is added by RE.** What you publish follows your deployment's normal rules unless its administrator configured a zone. A private investigation's output is the exception (see "Private investigations").
- **Draft is a status, not a place.** A finding you have not accepted is a draft; it is not held in a separate zone. The old draft zone was retired on 2026-10-08.
- **Egeria rolls forward.** RE does not undo a publish. Removing a tag removes its link; a corrected note is a later note; elements RE created stay in Egeria until the owner deletes them by hand.

### After a press

The page shows a short cue (**publishing…**) and then what Egeria reports back (**✓ in Egeria · published 10-11 · confirmed**, or a plain statement of what failed). A word on screen comes from what was read back from Egeria, never from the fact that you pressed a button. The three chips on a database page say the same in three places (see section 2): what Egeria holds, and **not checked since <time>** when RE has not asked lately. The identity is shown: **published as <you>**.

### What a database's survey report carries

A database's survey report in Egeria holds one annotation per finding. Which findings are included depends on how the report was published.

| Published by | What the report includes |
|---|---|
| **Running a Survey Definition** on the database (from Discovery, or `database survey-definition`), when it ran column profiling | The schema inventory, statistics, views and operations it measured, **and** the column-profiling results: one **DataClassMatch** annotation per column checked, one **ColumnValueSample** annotation recording how that column was sampled, a **ReferenceDataMatch** annotation for each low-cardinality column compared with a reference set, the JSON and XML column profiles (**NestedSchemaProfile**, **NestedColumnSample**), and any request for action (for example "propose a Data Class" for an unmatched column that follows a clear pattern). |
| **Publish** on the Curate page, or `database survey --egeria` | The survey you kept: schema inventory, statistics and views, **and** the latest stored data-class and reference-data verdicts (the ones shown on the **Data Class Match** and **Reference Data Match** cards), with their requests for action. The JSON and XML column profiles are not sent from here yet; a Survey Definition run sends those. |

What to expect from the column-profiling annotations:

- **Every column checked gets an annotation, not only the matches.** Each DataClassMatch annotation names its verdict:

  | Verdict | Meaning |
  |---|---|
  | `matched` | the column matches a Data Class |
  | `partial_match` | the column partly matches a Data Class |
  | `no_match` | the column matches none of the Data Classes it was compared with |
  | `unmatched_patterned` | no Data Class fits, but the values follow a clear pattern, so a new Data Class is proposed as a draft |
  | `inconclusive` | the sample could not settle a verdict |
  | `not_sampled` | no values were read from the column, so nothing was established; this is never "no match" |
  | `no_candidates` | Egeria had no Data Classes to compare against, or they could not be read |
  | `not_applicable` | the column cannot be sampled, for example a column of a view |

  A report on a wide database therefore carries many annotations, roughly two or three per sampled column.
- **The sample is stated, not implied.** Each ColumnValueSample annotation records the strategy, how many rows were read, out of how many, the seed and the date. A match is a statement about that sample, not about every row.
- **From Curate's Publish, the verdicts come from the latest stored batch, which may be older or newer than the survey you kept.** The **next publish** line names the batch, for example "data-class verdicts · 42 columns · measured 10-19". Each verdict says when it was measured, verdicts for columns no longer in the kept inventory are not sent (the press says how many), and a newer batch is published as new annotations rather than replacing the old ones.
- **A verdict is linked to its column when the column is in Egeria.** For a schema you committed on the **Contents** tab, Egeria's cataloger created the column elements, and each verdict is linked to its column (`AssociatedAnnotation`), once. For other schemas the verdict stays on the report, named by its column path.
- **Reports published before 2026-10-19 do not have these annotations.** Until then, column-profiling results were built but never sent. To add them, run the Survey Definition again; RE does not alter earlier reports.

### A re-run re-links, it does not duplicate

Since the profile reshape (#847, #859), a re-run re-links unchanged annotations and creates only the changed ones. The card line reads "N measures published · M changed since <time> · K re-used". (The card line is the audit's reading; not re-verified on 2026-10-28.)

### Scores in Egeria

Repository health, the FOSS scorecard and the SQL view complexity rating are published as Egeria **QualityAnnotations**. Egeria's QualityAnnotation has room for one whole-number score, and RE's ratings are several named numbers (for example `activity`, `community`, `freshness`, or `complexity_score` and `join_count`). So RE puts them in the annotation's **JSON properties**, under `qualityScores`, as numbers. (not re-verified on 2026-10-28; this is a claim about the code)

- **Read the scores from `qualityScores` in the JSON properties.** Egeria's own `qualityScore` field is not set by RE and shows `0`; that `0` is "not filled in", not a score of zero.
- **Reports published before 2026-10-19 hold no scores in Egeria.** Earlier versions sent the scores in a field Egeria does not have, and Egeria discarded it without an error. Publishing the resource again sends them.

**Not built yet in this section:** nothing; see section 10.

(screen words not re-verified on 2026-10-28)

---

## 7. Extending and customizing

You can add or change a lot **without touching Resource Explorer's code**. Each row says how, and where the change appears.

| You add or change | How | Where it appears |
|---|---|---|
| An analysis (library step) | a package with a StepManifest and a declaration (result kind, measures with unit and as-of, absence sentences, chat extents, confidence form, optional Egeria type), installed as a `trellis.analytics` entry point | the resource's Survey & analyses tab; its questions' headlines; Chat answers citing its rows; the Curate publish table row with "writes as" |
| A question | a row in resource_questions.csv (or Admin › Question Catalog's add) naming its stage, kinds, purposes, perspectives and answering analysis; the generator refuses a bare step name or a kind with no adapter | the stage's Questions tab, ordered by purpose |
| A perspective or a purpose | Dr.Egeria valid-value lists (purposes suggestive, free text kept) | the sidebar perspective filter; Investigation purposes; "NOT AMONG THIS INVESTIGATION'S PURPOSES" |
| A survey definition | a Dr.Egeria document naming steps and scoped-by questions | the Survey & analyses tab's definitions |
| Settings | Admin › Configure (value-profile share, annotation types, API fetch addresses, Egeria mounts, groups) | the cards' words and thresholds |
| A file-system reach | registration with host and container path (remote mechanisms: designed, not built) | the folder survey's reach line |
| A dashboard | Dr.Egeria Report and Dashboard Sheet (designed for RE in #903; built in the Portal today) | the Portal's local dashboards; RE's Dashboards tab when built |
| An open-data portal | designed (#904), OD1 in build | not yet |

### An analysis

The extension is a *declaration*: a small package says what its result is, which measures it makes (each with a unit and an "as of"), the sentence to show for each absence (the words in section 2), which questions it answers, how confident it is, and, optionally, which Egeria annotation type its measures write as. RE reads the declaration; it needs no change. The how-to is [extending-with-analyses.md](extending-with-analyses.md). The first worked example is `fs_permissions` on the `loading_bay` file system (the extensibility gate; its walk is in the tutorial once it has run).

### A question

A question is a row in `resource_questions.csv`: its stage, resource kinds, purposes, perspectives and the analysis that answers it. The generator refuses a row whose answering analysis is a bare step name or whose kind has no adapter. The same add is available under **Admin › Question Catalog**. The new question appears on its stage's Questions tab, ordered by purpose, and its id never changes afterwards.

### A perspective or a purpose

Perspectives and purposes are Dr.Egeria valid-value lists. Purposes are suggestive: free text is kept (see "Purposes", section 3). The perspective list drives the sidebar filter.

### A survey definition

A survey definition is a Dr.Egeria document that names the steps to run and the questions they are scoped by. It appears among the definitions on the resource's **Survey & analyses** tab.

### Settings

**Admin › Configure** holds the settings that change the cards' words and thresholds (section 8).

### A file-system reach

You register a file system with a host and a container path. The folder survey's reach line then says whether Egeria can read it. Remote mechanisms are designed and not built.

### A dashboard, an open-data portal

A dashboard is a Dr.Egeria Report and Dashboard Sheet. The design for showing them inside RE is #903; today they are built in the Portal. The open-data portal design is #904, with OD1 in build; there is nothing to use yet.

### The Analytic Library

The **Analytic Library** is a set of small, installable analyses that sit beside Resource Explorer's own. Each one is either a **routine** (it reads and counts) or a **step** (it can be part of a survey). Every result carries its own **state word**, one of *measured*, *nothing found*, *not established* or *not applicable*, so "we looked and found nothing" never looks like "we could not look". The library's guide for people who write them is [`../../trellis-analytics/README.md`](../../trellis-analytics/README.md).

Where you meet it:

- **Curate → By analysis** (for a database) shows **curation coverage**: how many of the database's schemas are published, not yet published, or blocked, with a **which** link that lists the names. The state word sits beside the counts. If the count could not be made, you see the state and the reason, not a table of zeros.
- **The Egeria Portal** can show the same numbers as a tile named **Trellis - Curation Coverage** (family *Curation*): a bar of published against not yet published, with the result's state as the subtitle and a line saying which version produced it and when. An administrator adds it to the Portal (see the library's README).
- **Other steps** an administrator installs show up as extra analyses on the resource, tagged with the stage they belong to.
- **From Egeria**, once the owner has declared a step to Resource Explorer's engine (for example `ResourceExplorerSurvey::re-database-staleness`), starting it on a database in Egeria runs the step in Resource Explorer. The results appear as a survey report in Egeria and in the database's Understanding list, beside *Resource Explorer: derived checks*.

**Not built yet in this section:** remote reach, Dashboards in RE, and the open-data portal; see section 10.

(screen words not re-verified on 2026-10-28)

---

## 8. Admin

Reachable from **⚙ Admin** in the header. This is system and catalog configuration, not something you do to curate one resource. It has these groups:

- **Configure**: Value profile settings, **Annotation Types** (the registry of metadata annotation schemas: what each one means, its properties, and its mapping to Egeria's own property classes), **Question Catalog**, **API fetch addresses**, **Egeria mounts**, and **Groups** (group related repositories, databases and file systems; assigning one resource to a group is done from that resource's own record; each group with members is a Folio in Egeria, see Curate; deleting a group removes each member from the Folio at that member's next Publish, and the Folio itself stays, the owner deletes it by hand).
- **Observe**: **Logs**, **Publish Queue** and **Feedback**.
- **Reconcile**: **Egeria Alignment**, **Egeria Links** and **Repair**.
- **Prefect**.
- **Repository discovery sources**: named, reusable "where do we scout" configurations, picked from Scouting's Discover sub-tab instead of re-typing a search. A **search**-type source holds the same filters the ad-hoc form uses; a **list**-type source holds a pasted set of GitHub URLs. Delete a source here; there is no edit-in-place yet, so delete and recreate.

(This section follows the audit's list of the Admin groups; the pages were not re-verified on 2026-10-28.)

The old Schedules monitoring page is replaced by **⏱ Schedules** under Automate.

---

## 9. The CLI

The CLI caches a session so you are not asked on every command (CLI; no screen):

```bash
uv run resource-explorer login              # prompts for your password
uv run resource-explorer logout
```

Commands that read local data (`list`, `ask`, `runs list`, a plain `survey`) work without a session. Commands that reach Egeria (`survey --publish`, `egeria-recheck`, `curate materialize`, `analysis run --publish`) need a live session and say so in one line if you do not have one:

```
session expired at 14:07, run `resource-explorer login`
```

```bash
# Survey a repo
uv run resource-explorer survey my-repo

# Survey and publish to Egeria
uv run resource-explorer survey my-repo --publish

# Register, list, and survey file systems
uv run resource-explorer filesystem register my-data --local-path /Users/dwolfson/localGit/data --canonical-path file://shared-nfs/data
uv run resource-explorer filesystem list
uv run resource-explorer filesystem survey my-data            # local walk and profiling
uv run resource-explorer filesystem survey my-data --egeria   # survey and publish to Egeria

# Interactive chat
uv run resource-explorer chat

# Ask a one-shot question
uv run resource-explorer ask "how many files does my-repo have?"
```

---

## 10. Not built yet

Each item is a design, not a screen. The date is when this list was last checked against the app.

| Item | Where it is designed | Checked |
|---|---|---|
| Renderers for seven result kinds (the screen says "planned, not built yet") | `DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE.md` | 2026-10-28 |
| Dashboards inside RE | `DESIGN-LOCAL-DASHBOARDS-DECLARED-ANALYTICS.md` (#903) | 2026-10-28 |
| Open data | `DESIGN-OPEN-DATA-RESOURCE-KIND-BRAINSTORM.md` (#904); OD1 in build | 2026-10-28 |
| Remote reach for file systems | `DESIGN-FILES-REMOTE-REACH.md` | 2026-10-28 |
| An Artifacts tab on Understanding | `DESIGN-ARTIFACTS-VIEW-AND-DOC-LINKS.md` | 2026-10-28 |
| The winnowing bench (winnowing columns on a work list, #843) | `DESIGN-WORK-LISTS-WINNOWING-AND-MIXED-KINDS.md` | 2026-10-28 |
| Mixed-kind work lists | `DESIGN-WORK-LISTS-WINNOWING-AND-MIXED-KINDS.md` | 2026-10-28 |
