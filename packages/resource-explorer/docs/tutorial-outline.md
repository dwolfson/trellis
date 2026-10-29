# Resource Explorer tutorial — outline for review

**Status:** outline only, for the project owner's review. No prose and no screenshots are written yet.
**Date:** 2026-10-29.
**Replaces, once written:** the six walks in [`tutorial/`](tutorial/README.md), which stay on `main` until then.

## How to read this outline

- Each part has a goal, what the reader needs first, numbered steps, what the reader sees after each step, and what
  can go wrong.
- Screen words are in quotation marks. Each set of screen words comes from one of three places, marked after it:
  - **(seen)**: read on the running app on 2026-10-28 or 2026-10-29, by the user guide or the merged walks;
  - **(code)**: read in the app's source on 2026-10-29, not seen on a screen. This writer's browser was not signed in.
    The prose writer must check these on the screen;
  - **(not yet confirmed)**: from the user guide, which says it could not open that screen either.
- Decisions the owner needs to make before prose starts are marked **Owner decision needed**. Section 8 lists them
  with the rulings given so far.

**This is the Core tutorial.** It is one of three (owner ruling, 2026-10-29):

- **Getting Started:** install and configure Trellis and Resource Explorer. Not written yet.
- **Core (this one):** use Resource Explorer on your own data sources, from sign-in to publishing.
- **Advanced:** Automate, adding your own analyses and other extensions, Admin, and more. Not written yet.

---

## 1. The reader and the promise

**Who this is for.** A data steward or data engineer. They know databases, files and data catalogs. They have never
used Resource Explorer or Egeria.

**What they can do at the end.**

1. Say in two sentences what Resource Explorer is for and when to use it.
2. Sign in, find their way around the screen, and know what each area is for.
3. Start an investigation that records why they are looking at a set of data sources.
4. Add a database, a file system and a code repository, and find each one again.
5. Read what Resource Explorer found about a data source, stage by stage. They can tell "nothing was found" from
   "nobody has looked yet".
6. Add what only they know, such as an owner and how sensitive the data is.
7. Ask a question in plain words, and check which stored results the answer came from.
8. Decide what to send to the Egeria catalog, send it, and check that it arrived.
9. Compare several data sources side by side in a work list.
10. Know where to go next.

**How long it takes.** About two and a half hours in total, in parts of 10 to 25 minutes. Each part ends at a natural place to
stop. A sign-in lasts about an hour, so the reader will be asked to sign in again at least once. Part 2 says so before
it happens.

**What the tutorial does not cover.** Installing and configuring Trellis, Resource Explorer or Egeria (the Getting
Started tutorial). Automate, adding your own analyses, questions or survey definitions, and Admin (the Advanced
tutorial). The command line. "Where to go next" (part 13) points to each.

---

## 2. The parts, in order, and why this order

| # | Part | Needs Egeria running | Needs sign-in | Needs data already loaded | Writes something |
|---|---|---|---|---|---|
| 1 | What Resource Explorer is for | no | no | no | no |
| 2 | Sign in and find your way around | yes (Egeria checks the password) | yes | no | no |
| 3 | Start an investigation | yes | yes | no | yes, in Resource Explorer; also in Egeria if "Create in Egeria" is chosen |
| 4 | Add data sources and find them again | yes | yes | a reachable database, folder and repository | yes, in Resource Explorer only |
| 5 | The stages a data source goes through | yes | yes | one surveyed data source | no |
| 6 | Run a survey and read the first answers | yes | yes | the data source from part 4 | yes, in Resource Explorer only |
| 7 | Discovery, Assessment and Analysis: read the answers | yes | yes | a surveyed data source | no (yes if the reader presses "run") |
| 8 | Enrichment: add what only you know | yes | yes | a data source | yes, in Resource Explorer only |
| 9 | Ask in chat and check the sources | yes | yes | a surveyed data source | yes, a stored chat turn |
| 10 | Curate: decide what goes to the catalog | yes | yes | a surveyed data source | yes, in Resource Explorer only |
| 11 | Publish to Egeria and check that it arrived | yes, and writable | yes | a curated data source | **yes, in Egeria** |
| 12 | Work lists: compare several data sources | yes | yes | three or more data sources of one kind | yes, in Resource Explorer only |
| 13 | Where to go next | no | no | no | no |

**Why this order.**

- **Purpose before buttons (1).** A new reader needs to know what problem the tool solves before any screen means
  anything. The old walks began at the sign-in panel.
- **Investigation before data sources (3 before 4).** When an investigation is current, adding a data source offers
  "add to <name>" (seen). Doing it in this order means the reader's data sources land in a scope straight away, instead
  of being sorted afterwards.
- **One data source end to end, the others briefly (4 to 11).** The reader follows one database through every stage.
  A database is the kind of source this reader knows best. Repositories and file systems are added in part 4 and get
  a short "how this differs" note in later parts. **Decided (D1):** a database is the main example. The reader is told
  early that each kind of data source has its own Curate page, but the structure is the same, and part 10 shows all
  three.
- **The map of stages before the stages (5 before 6 to 10).** The six stages are the spine of the screen. The reader
  sees the whole strip once, with one sentence per stage, before going into any of them.
- **Read before you change (6 to 8 before 10 and 11).** The reader learns what was measured before deciding what to
  publish.
- **Chat after the stages (9 after 6 and 7).** A chat answer is built from stored results. Those exist only after a
  survey has run, so chat makes sense once the reader has seen results on the page.
- **Curate, then Publish (10, then 11).** Every Curate choice saves in Resource Explorer only. Egeria changes only when
  the reader presses Publish (seen). Keeping these as two parts makes that rule hard to miss.
- **Work lists late (12).** A work list compares several data sources against one stage's questions. It needs both
  several data sources and an understanding of a stage.
- **Where next last (13).** It points to the Getting Started and Advanced tutorials and the guides. The brief asked
  for "admin settings a user meets"; the owner moved Admin to the Advanced tutorial (D5).

**The setup the tutorial assumes.** A running Egeria with the Coco Pharmaceuticals sample, a Resource Explorer
connected to it, an Egeria user id and password for the reader, one PostgreSQL database the reader can reach with a
read-only account, one folder Egeria can read, and one public GitHub repository. **Decided (D2):** the tutorial names
one sample setup, so every reader sees the same screens (gap G1). The Getting Started tutorial sets it up. Which
database, folder and repository it uses is still to be chosen.

---

## 3. The parts

### Part 1 — What Resource Explorer is for

**Goal.** Know what Resource Explorer does, how it relates to Egeria, and when to use it.

**Before you start.** Nothing.

**Content (no steps; one page, one diagram).**

1. The problem: your organization has many databases, file shares and code repositories. Nobody can say what is in
   each one, who owns it, or whether it can be trusted.
2. What Resource Explorer does: it looks at a data source, measures it, asks you what only a person knows, and lets
   you publish what you have learned to a shared catalog.
3. What Egeria is: an open-source metadata catalog. It holds the shared record. Resource Explorer reads from it and
   writes to it, always as you.
4. The flow in one picture: add a data source → survey it → read the answers → add what you know → choose what to
   publish → publish → check it in Egeria.
5. Three promises the tool keeps, each in one sentence:
   - nothing reaches Egeria until you press Publish;
   - "nothing found" and "not looked at yet" are always shown differently;
   - every answer can show where it came from.

**What can go wrong.** Nothing on screen. The risk is in the writing: do not explain Egeria's architecture here. One
sentence and the glossary are enough.

---

### Part 2 — Sign in and find your way around

**Goal.** Sign in and know what each area of the screen is for.

**Before you start.** The address of your Resource Explorer (for example `http://localhost:8813/`), your Egeria user
id and password.

**Steps.**

1. Open the address in a browser.
   - *You see:* a panel headed "Resource Explorer" and "EXPERIMENTAL UI", with "Sign in with your Egeria user id to
     continue.", an "Egeria user id" box, a "Password" box and a "Sign in" button (seen).
2. Type your Egeria user id and password, then click **Sign in**.
   - *You see:* the main screen. Your user id and **Sign out** are at the top right (seen).
   - *Explain:* there is no separate Resource Explorer account. Egeria checks your password once and Resource Explorer
     does not keep it. Everything you do from now on is recorded in Egeria under your user id.
3. Look at the strip across the top: "Investigation · 1 Scouting · 2 Discovery · 3 Assessment · 4 Analysis ·
   5 Enrichment · 6 Curate · Understanding · Automate · ▦ Work lists" (seen).
   - *Explain in one line each:* Investigation is why you are looking; 1 to 6 are the stages a data source goes
     through, left to right; Understanding shows a data source over time; Automate repeats a run on a schedule; Work
     lists compare several data sources. Part 5 goes into the stages.
4. Look at the left sidebar: **Repos**, **DBs** and **FS** (repositories, databases, file systems), a filter box, the
   **INVESTIGATION** picker, and **Work lists** (seen).
5. Look at the right-hand rail: "ASK scoped to <data source>", a box, **Ask** and **what would answer this?** (seen).
   Part 9 uses it.
6. Look at the header: **Activity** (a log of everything that has run), **Admin**, the current investigation, your user
   id, **Sign out** (seen).
7. Click **Activity**, read the latest entries, and close it.
   - *You see:* "the most recent 300 entries, latest first", a filter box and **all / ok / error / running** (seen,
     user guide).

**What can go wrong.**

- Wrong password: the panel stays, with a message. (Exact words: not yet confirmed.)
- Egeria is not running: the sign-in fails, because Egeria is what checks the password. (Exact words: not yet
  confirmed.)
- After about an hour: a "Signed out" banner with a **Sign in** button (seen, user guide). Sign in again and carry on;
  nothing you saved is lost.
- The header can read "not signed in" while you are signed in, when no investigation is chosen. This is a known
  screen defect (gap G9). Tell the reader to ignore it until the fix lands.

---

### Part 3 — Start an investigation

**Goal.** Create an investigation that says why you are looking at a set of data sources, and make it current.

**Before you start.** Part 2.

**Steps.**

1. Click **Investigation** at the left of the strip.
   - *You see:* "An investigation is the frame a body of work runs inside — why it exists, not what kind of work it
     is." and a table: INVESTIGATION, PURPOSES, STATUS, SCOPE, EGERIA (seen).
2. Click **+ New investigation**.
   - *You see:* a "New investigation" dialog with Name, Description, Purposes, Kind and "Where it lives", and
     **Create** and **Cancel** (code).
3. Type a name, for example "Learning Resource Explorer", and a one-line description.
4. Choose one or two purposes, for example "Explore" and "Learn".
   - *Explain:* the purposes put the most relevant questions first on every stage. You may type one that is not in the
     list; it is kept, with a small "not in the list" cue (seen, user guide).
5. Leave **Kind** at "Study".
   - *Explain in one line each:* Study, Task, Campaign, Personal, Experiment (code). Personal and Experiment are private
     to you; Experiment also asks for a hypothesis. Do not choose a private kind for this tutorial: a private
     investigation cannot publish a database or a file system yet (seen, user guide).
6. For **Where it lives**, choose **Ad-hoc** ("Stays local. Nothing is written to Egeria") (code).
   - *Explain:* Ad-hoc is the simplest place to start. The investigation stays in Resource Explorer, and you can
     promote it to Egeria later. The other choice, "Create in Egeria", is the default; it creates a project in Egeria
     at once so others can share it. The dialog's default is "Create in Egeria", so the reader must change it
     (gap G3). **Decided (D3).**
7. Click **Create**.
   - *You see:* the new investigation's page, with **Make current**, Edit, Reclassify…, Suspend and Close, and a "Next
     steps" box (seen on another investigation).
8. Click **Make current**.
   - *You see:* the button now reads "Current investigation" (code), the header shows the investigation's name, and the
     sidebar shows "SCOPE · 0" under it (seen, user guide, for another name).

**What can go wrong.**

- No name: the dialog shows a message under the fields and does not create anything. (Exact words: code, to confirm.)
- Experiment without a hypothesis: refused, with a message (code).
- The EGERIA column on older rows can read "unbound by reset". Explain it as: "this investigation's Egeria project was
  lost when the Egeria server was reset; it can be linked again". See gap G12.

---

### Part 4 — Add data sources, and find them again

**Goal.** Register a database, a file system and a repository, and find each one in the sidebar.

**Before you start.** Part 3. For the database: host, port, database name, and a read-only user name and password. For
the file system: a folder path that this server can read. For the repository: its GitHub address.

**4a. A database.**

1. In the sidebar, click **DBs**, then **＋ Find databases** at the foot of the list (code).
   - *You see:* a "Find databases" dialog: "Run a saved source, or discover on a server once. Nothing is registered
     until you confirm.", with tabs "Saved sources", "Discover on a server" and "From a file" (code).
2. Click **Register one database…** (code).
   - *You see:* "Register one database" and "Test the connection first; Register is available once the test has passed
     for what is typed here. Nothing is sent to Egeria." (code).
3. Fill in **Slug**, **Display name**, **Host**, **Port**, **Database**, and under "Credential", **Username** and
   **Password** (code).
   - *Explain "Slug":* a short name with no spaces that Resource Explorer uses in addresses, for example
     `sales_db`. The screen uses the word, so the tutorial must explain it (gap G6).
   - *Explain:* use a read-only account. The first stages read only the database's own catalog: tables, columns,
     keys, comments and row estimates. Resource Explorer asks for more only when a later step needs to read rows, and
     says which step and why (seen, user guide). The password is stored encrypted and never shown again.
   - Leave "Egeria connection (optional)" closed (code). See gap G7.
4. Click **Test connection**.
   - *You see:* the button reads "Testing…", then a result beside it (code).
5. Click **Register**.
   - *You see:* "It is in the database list now. Nothing was sent to Egeria." and **Register another** (code).
6. Close the dialog. Type the display name into the **DBs** filter box and click the row.
   - *You see:* the database's page. If an investigation is current, an "add to <name>" action (seen, user guide).
7. Click **add to <name>**.
   - *You see:* "already in <name>'s scope", and the sidebar's "SCOPE" count goes up by one (seen, user guide).

*What can go wrong (database).*

- The test fails: "Connection failed" or the database's own message, and **Register** stays disabled (code).
- Signed out meanwhile: "Sign in to test a connection." (code).
- The header reads "never surveyed · not published to Egeria". On a new database that is true. On a database that has
  been published it is a known defect (gap G11).

**4b. A file system.**

1. Click **FS**, then **＋ Add a file system** (code).
   - *You see:* "Add a file system" and "Registering stores it here. Nothing is sent to Egeria." (code).
2. Fill in **Slug**, **Display name** and **Mount (local path)** (code).
   - *You see:* beside the path, "◔ checking", then "✓ readable here", or a warning (code).
3. Leave **Canonical mount (blank = the mount)** empty (code). See gap G5.
4. Click **Register**, then find the file system in the **FS** list and add it to the scope as in 4a, steps 6 and 7.

*What can go wrong (file system).*

- "⚠ this server can't read this path · you can still register" or "⚠ this is a file, not a folder · you can still
  register" (code). Explain: registering still works, but no survey can read the folder until the path is right.
- "✕ already registered": that short name is taken (code).

**4c. A repository.**

1. Click **Repos**, then **＋ Find repos** (seen).
   - *You see:* two ways in, a search and "From a list" (seen, user guide).
2. Choose **From a list** and paste one GitHub address.
3. Tick the row and click **Import Selected**.
   - *You see:* the button reads "Importing…", the row shows its own state, and the repository appears in the sidebar
     (seen, user guide). Nothing is registered until you click Import Selected.
4. Find the repository and add it to the scope as in 4a.
   - *Explain:* a new repository reads "not yet surveyed", not zero. Its numbers arrive with its first survey (part 6).

**4d. Finding things again.**

1. Use the filter box under **Repos**, **DBs** or **FS**.
2. For repositories, the chips **In scope**, **All**, **New**, **Surveyed** and **Published** narrow the list (seen).
3. The **PERSPECTIVE** chips (Admin, Data Owner, Steward and others) narrow the questions to who is asking (seen).
   Leave them all off for this tutorial.

---

### Part 5 — The stages a data source goes through

**Goal.** Know what each of the six stages is for, and how every stage page is laid out.

**Before you start.** Part 4. One data source that has already been surveyed, so the pages have something on them.
(Use a sample data source; the reader's own one is surveyed in part 6.)

**Steps.**

1. Click a surveyed data source in the sidebar, then **1 Scouting**.
2. Read the six stages, one plain sentence each:
   - **Scouting:** a fast first look. What is it, how big, is it alive?
   - **Discovery:** what is in it, and is it already in the catalog?
   - **Assessment:** a closer look at quality, security and documentation.
   - **Analysis:** its structure, such as components, dependencies and relationships.
   - **Enrichment:** what only a person knows: owner, sensitivity, intended use.
   - **Curate:** choose what to publish to Egeria, then publish.
3. Point at the tabs every stage opens: **Questions**, **Survey & analyses**, **By analysis**, **Disposition** (seen).
   - *Explain:* Questions shows answers; Survey & analyses shows what ran to produce them. By analysis and Disposition
     are covered later or left out (see section 5).
4. On the **Questions** tab, read the first line, for example "6 of 6 answered · Scouting", and the key beneath it
   (seen).
5. Read the marks, using the table in part 6 of the prose (one table, taught once):
   - ✓ answered · ∅ nothing found · ◐ partly · ○ not run · ◌ no way to answer yet · ? could not tell · ⚠ needs you ·
     ◔ running · ✕ failed (seen, user guide).
   - *Explain:* ∅ means it was measured and there was nothing. ○ means nobody has run it. They are never the same.
6. Open one question row. Point at **why is this here**, the answer, the source line, **re-run**, **the numbers
   behind this ›** and **ask in chat ›** (seen).

**What can go wrong.**

- A count such as "5 of 19 answered · 13 still loading" stays for many seconds without saying what it waits for
  (seen). Tell the reader to wait until "still loading" goes. Gap G10.
- A ✓ beside an answer that says nothing could be checked, for example "not checked: 0 of 65 declared dependenc(ies)
  could be queried" (seen). Tell the reader to read the words, not only the mark. Gap G13.

---

### Part 6 — Run a survey and read the first answers

**Goal.** Run the first survey on your own database and read what Scouting found.

**Before you start.** Part 4 (your database) and part 5.

**Steps.**

1. Open your database, click **1 Scouting**, then the **Survey & analyses** tab.
   - *You see:* "ANALYSES RUN", "NEED YOU", "LAST SURVEY", then "SURVEY DEFINITIONS" and a list of analyses, each with
     **Run →** (seen on a repository).
   - *Explain "survey":* a survey is a set of checks run together. Each check is an analysis.
2. Click the survey's start button. **Owner decision needed (D4):** which button a first-time reader presses on a
   never-surveyed database. The screen offers several and none is marked "start here" (gap G4).
   - *You see:* "◔ running", an entry in **Activity**, and a short notice with **View** when it finishes (seen, user
     guide).
3. Click the **Questions** tab.
   - *You see:* the count rise as answers arrive.
4. Read three answers and their source lines.
5. Click **the numbers behind this ›** on one of them.

**What can go wrong.**

- The account cannot see everything. Answers then say "measured within what this account can see", and counts read
  "3 of 26", not "3" (seen, user guide).
- A step needs another step first. If it is cheap, it runs and says so afterwards, for example "Ran
  postgres_schema_and_stats first, then postgres_column_profile." If it is costly, the row asks first: **Run it** or
  "not now — nothing has run" (not yet confirmed). The prose must explain this without the step names (section 5).
- A step needs to read rows and the account cannot. The row offers three choices: run what this account can answer,
  pick a broader account, or ask the database owner (seen, user guide).
- The run fails: "✕" with the reason, and an Activity entry marked error.

*Repository and file system differences (short notes).* A repository's header shows numbers such as stars, forks,
contributors and size; "? not read" means the step has not run, not zero (seen). A file system's survey page shows who
can read the folder ("✓ Egeria can read <path>"), counts, the deepest folders and files that describe their folder
(seen). Its seven start buttons need an order (gap G4).

---

### Part 7 — Discovery, Assessment and Analysis: read the answers

**Goal.** Read the middle three stages and tell a real answer from a gap.

**Before you start.** Part 6.

**Steps.**

1. Click **2 Discovery**. Read "Has this resource already been cataloged in Egeria, and when?", "Is there any existing
   use within our organization?" and "Any known feedback?" (seen).
   - *You see:* where nothing is recorded, "Nothing is recorded for this — a real absence, not an unrun analysis."
     (seen).
2. Click **3 Assessment**. Read two answers. (Not yet confirmed on a database.)
3. Click **4 Analysis**. Find a row marked ○ and read "Nothing has been measured for this yet." (seen).
4. On that row, point at **run** and explain what it would do. The reader may press it on their own database.
5. Find a row marked ◌ and read it.
   - *Explain:* ◌ means there is no way to answer it automatically yet. It is not a failure.
   - "🔔 notify me" on a row is left to the Advanced tutorial (D5).

**What can go wrong.** Slow panes (gap G10). A database Discovery tab took 9 to 15 seconds in the audit.

---

### Part 8 — Enrichment: add what only you know

**Goal.** Record the owner, the sensitivity and the intended use of your database.

**Before you start.** Part 4.

**Steps.**

1. Click **5 Enrichment**, then the **Context** tab.
   - *You see:* "Everything a person has supplied about this resource — each row signed and dated, and each saying what
     it feeds. Nothing here is written to the Egeria until you publish it (Curate)." (seen).
2. Under "What we judge", set **Sensitivity** to "internal", **Owner** to a name, and **Intended use** to "Explore".
   - *You see:* each field signed with your user id and the date, and a line saying what it feeds, for example
     "feeds → Curate (publish record)" (seen).
3. Under "What we record", set **Environment** to "dev".
4. Under "What only you can answer", click **Answer this →** on one question and answer it.
5. Click **RFAs** in the strip.
   - *Explain:* "RFA" stands for "request for action": something a check could not settle and a person must. Open one,
     read it, and close the drawer without acting (gap G15).

**What can go wrong.**

- The tab reads "Reading what's been supplied…" for several seconds (seen). Wait.
- A field says "feeds → kept in Resource Explorer · no publish step reads it yet" (seen). Explain: it is saved, but
  nothing sends it to Egeria today.

---

### Part 9 — Ask in chat, and check the sources

**Goal.** Ask a question in plain words and check which stored results the answer came from.

**Before you start.** Part 6, so there are stored results to answer from.

**Steps.**

1. With your database open, look at the rail: "ASK scoped to <your database>" (seen).
   - *Explain:* the question is about this data source. You do not type its name.
2. Type "How many tables have no primary key?" and click **Ask** (or press Ctrl+Enter / ⌘+Enter).
   - *You see:* "Asking…", then "Answering…", then the answer (code).
3. Read the line under the answer, for example "From 3 stored results · …" followed by the names of the analyses it
   used (code; seen by the architect on a file system).
   - *Explain:* the answer is built only from results Resource Explorer has stored. That line names them. If it says
     "No compiled evidence on this answer · source not reported" (code), the answer did not say where it came from:
     treat it with care.
4. Click **ask in chat ›** on a question row (part 5) and see the question arrive in the rail.
5. Type a question, then click **what would answer this?** instead of Ask.
   - *You see:* which analyses would answer it, which have stored results, and which have never run, with **Run** on
     those (code).
6. Click **Was this right?** and mark the answer.
7. If an investigation is current, click **add to investigation journal** and read the dialog: "Add this turn to the
   investigation journal?" with **Add** and **Not now** (code). Click **Not now**.

**What can go wrong.**

- No data source chosen: "Select a resource first: a compile reads one resource's stored results." (code). The word
  "compile" is internal (section 5, gap G16).
- The analysis that would answer it never ran: the rail says "N not run" and offers **Run** (code).
- A long run: "Still running after five minutes: stopped watching here. The run itself has not failed." (code).

---

### Part 10 — Curate: decide what goes to the catalog

**Goal.** Choose what Resource Explorer will send to Egeria for your database: which schemas, tags, a group, your
rating and notes.

**Before you start.** Parts 6 and 8.

**Steps.**

1. Click **6 Curate**.
   - *You see:* tabs including "Describe and publish" and "Contents" (seen on a database). See gap G14: the user guide
     says a database's Curate is one page; the walk saw tabs.
2. On **Contents**, read "What gets published" and the three chips: "published by RE", "attached N schemas" and
   "cataloged by Egeria N schemas", each with ✓ or "◌ not checked since <time>" (seen).
   - *Explain:* a chip says what Resource Explorer saw the last time it asked Egeria, not what Egeria holds right now.
3. Choose **Include** for one schema and **Leave out** for another.
   - *You see:* the choice saved at once in Resource Explorer. Nothing goes to Egeria yet (seen, user guide).
4. On **Describe and publish**, under "FINDABLE", add a tag, for example "learning".
   - *Explain:* tags are public in Egeria once published, and shared: everyone's "sales" is the same tag.
5. Choose a group, or leave "Ungrouped".
6. Under "WHAT PEOPLE SAY", give a rating and write a note.
   - *You see:* "saved · will publish" beside each (seen, user guide).
   - *Explain:* your rating and notes are published under your name, publicly. Each person has one rating per data
     source.

7. Open the Curate page of your repository, then of your file system, and compare them with the database's (D1).
   - *Explain:* every kind has the same shape: what is chosen for publishing, how to find it (tags and group), what
     people say (ratings and notes), and one Publish band at the foot. What differs is what you choose from.
   - *Repository:* three tabs, "Describe and publish", "Contents" (files and folders, Include or Leave out) and
     "Structure" (its components and dependencies) (seen, user guide).
   - *Database:* schemas and tables to include, the three chips, glossary terms, quality checks (seen). The exact tab
     layout must be read on the screen (gap G14).
   - *File system:* tags, group, ratings and notes, and a Publish that "attaches the root folder only" (seen).

**What can go wrong.**

- "not permitted · <reason>": Egeria's security does not let you change this element (seen, user guide).
- The sentence above the chips and a chip disagree about a count. Known defect (gap G11).
- *File system:* Curate reads "Nothing to review for file systems yet." (seen), although the survey page says "a
  proposal · confirm it on Curate". Gap G8.

---

### Part 11 — Publish to Egeria, and check that it arrived

**Goal.** Send your choices to Egeria and confirm that Egeria holds them.

**Before you start.** Part 10. Egeria running and writable for your user id. **Owner decision needed (D6):** which data
source the reader publishes, and whether the screenshots come from a throwaway database. This is the one part that must
write to the shared catalog (gap G2).

**Steps.**

1. Scroll to the foot of **Describe and publish**, to "PUBLISH TO EGERIA".
2. Read "next publish": what the press will send (seen, user guide).
   - *Explain:* one press sends the survey report, the tags and group, documentation links, and your own rating and
     notes. Never anyone else's.
3. Click **Publish**.
   - *You see:* "◔ publishing…" at once, then a result (seen, user guide).
4. Read the result line, for example "✓ in Egeria · published 10-25 · confirmed" (seen).
   - *Explain:* "confirmed" means Resource Explorer read it back from Egeria afterwards. It is not just "the button was
     pressed".
5. Click **Show in Egeria ▸** (or "Egeria reports" on a database) and read the report rows: "Survey: <name> · surveyed
   … · N annotations" (seen).
   - *Explain "annotation":* one measurement or observation, attached to the data source in Egeria.
6. Go back to **Contents** and read the chips again: "published by RE" now counts this press.
7. Check from Egeria's side: open the data source in the Egeria Portal (or another Egeria tool) and find the tag and the
   survey report. **Gap G17:** the tutorial needs one named place in Egeria to look.

**What can go wrong.**

- A pop-up says what failed and why, with **Retry** where retrying can help. The failed item keeps "not sent ·
  <reason>" (seen, user guide).
- "◐ behind · N annotations": Egeria holds an older report than the one Resource Explorer has kept. Publishing again
  sends the newer one (seen). Gap G18 on the words.
- "◐ partly committed · 4 queued" (seen). Meaning not yet explained anywhere a reader can find it. Gap G18.
- Explain once: Egeria rolls forward. Resource Explorer does not undo a publish. Removing a tag removes its link at the
  next press; a corrected note is a new note.

---

### Part 12 — Work lists: compare several data sources

**Goal.** Put several data sources of one kind side by side against one stage's questions, and move the best into
your investigation.

**Before you start.** Three or more data sources of one kind. Repositories are easiest to import in bulk (part 4c).

**Steps.**

1. In the sidebar, click **Select several…** (seen).
2. Tick three repositories, then click **save as work list…** (seen).
3. Name the list and save it.
   - *You see:* "▦ Work lists" in the strip count one more (seen).
4. Click **▦ Work lists** and open your list.
   - *You see:* rows of data sources against one stage's questions: "Compare a set of resources as rows x questions"
     (seen).
5. Pick a stage and read across the rows.
6. Narrow the list to the ones that matter (**promote**) (not yet confirmed).
7. Click **Add to an investigation…** or **Start an investigation from this list…** (code).

**What can go wrong.**

- A list holds one kind only. Mixed lists are not built (seen, user guide).
- Lists whose names start with `suggested-to-` are not work lists. They hold things other people pointed you at (seen,
  user guide).
- Creating a list writes only to Resource Explorer.

---

### Part 13 — Where to go next

**Goal.** Know what to read or do after this tutorial.

**Before you start.** Nothing.

**Content (no steps).**

- **The Advanced tutorial** (not written yet): Automate (schedules and "notify me"), adding your own analyses,
  questions, purposes and survey definitions, Admin and the settings it holds, and other topics still to be listed.
- **The Getting Started tutorial** (not written yet): installing and configuring Trellis and Resource Explorer, and
  setting up the sample this tutorial uses.
- The [user guide](user-guide.md) for every screen in detail.
- The [admin guide](admin-guide.md) for running Resource Explorer.
- The command line (user guide, section 9).
- Egeria's own documentation for the catalog itself.

The Admin and Automate steps that were drafted here move to the Advanced tutorial's outline (D5).

---

## 4. Glossary

Plain definitions, one or two sentences each. The tutorial links each term to this list the first time it appears.

| Term | Definition |
|---|---|
| **Resource Explorer** | A web tool that looks at data sources, measures them, records what people know about them, and publishes what it learns to Egeria. |
| **Egeria** | An open-source metadata catalog: the shared record of what data an organization has. Resource Explorer reads from it and writes to it. |
| **Catalog** | The shared record of data sources and what is known about them. Here, the catalog is Egeria. |
| **Data source (resource)** | Something that holds data: a database, a file system or a code repository. The screen says "resource"; the tutorial says "data source" and notes once that they are the same. |
| **Repository** | A code repository on GitHub. Resource Explorer reads its files and history. |
| **Database** | A PostgreSQL database. Resource Explorer reads its catalog first, and its rows only when you allow it. |
| **File system** | A folder, and everything under it, that this server or Egeria can read. |
| **Register** | Tell Resource Explorer about a data source so it can look at it. Registering writes nothing to Egeria. |
| **Slug** | The short name with no spaces that Resource Explorer gives a data source, used in addresses. You choose it when you register. |
| **Investigation** | A record of why you are looking at a set of data sources: a name, a description and its purposes. |
| **Purpose** | What an investigation is for, such as Explore or Learn. Purposes put the most relevant questions first. |
| **Scope** | The data sources an investigation covers. It can mix databases, file systems and repositories. |
| **Current investigation** | The one you are working in now. New data sources can be added to its scope in one click. |
| **Stage** | One of the six steps a data source goes through: Scouting, Discovery, Assessment, Analysis, Enrichment, Curate. |
| **Question** | One thing Resource Explorer asks about a data source, such as "Is this repository actively maintained?". Each stage has its own. |
| **Answer** | What Resource Explorer found for a question, with the source it came from. |
| **Analysis** | One check that measures something, such as counting tables or finding files no one has opened. |
| **Survey** | A set of analyses run together on one data source. |
| **Survey report** | The results of one survey, as Egeria stores them. |
| **Measure** | A number an analysis produced, with its unit and the time it was taken. |
| **Annotation** | One measurement or observation attached to a data source in Egeria. A survey report holds many. |
| **"as of"** | The time a number was read. Numbers from a source that changes carry one. |
| **Nothing found / not run** | "Nothing found" means it was measured and there was nothing. "Not run" means nobody has looked. They are never the same. |
| **Enrichment** | What a person adds that no check can measure: owner, sensitivity, intended use. |
| **Request for action (RFA)** | Something a check could not settle and a person must. The **RFAs** drawer lists them. |
| **Curate** | Decide what Resource Explorer will send to Egeria. Every choice is saved in Resource Explorer only. |
| **Include / Leave out** | The choice, per schema, table, file or folder, of whether it is published. |
| **Tag** | A public label in Egeria, such as "sales". Everyone's tag of the same name is one tag. |
| **Group** | A set of data sources that belong together, such as one product's. In Egeria a group becomes a collection. |
| **Rating and note** | Your judgment of a data source. Published under your name; one rating per person. |
| **Publish** | Send your choices to Egeria. Only a person's press publishes, and only that person's own work. |
| **Confirmed (read back)** | Resource Explorer read the published item back from Egeria and found it there. |
| **Work list** | A set of data sources of one kind, laid out side by side against one stage's questions, to compare them. |
| **Disposition** | Your verdict on a data source within an investigation, such as tracking, using or abandoned. |
| **Perspective** | Who is asking, such as Data Owner or Steward. Choosing one narrows the questions. |
| **Activity** | The log of everything that has run or been published. |
| **Credential** | The user name and password Resource Explorer uses to read a database. Stored encrypted. |
| **Mount (local path)** | Where the folder of a file system is found on this server. |

**Terms the tutorial avoids altogether** (they stay in the user guide): Folio (say "group"), zone, governance zone,
intent (say "stage"), annotation type names (QualityAnnotation, DataClassMatch and others), GUID, Egeria Project (say
"Egeria" or "shared"), valid-value list, data class, reference data, blueprint, component partition, confidence,
Architecture Recovery, Understanding and Automate beyond one line each (both are for the Advanced tutorial), library,
routine, step, Prefect, compile, extent, canonical mount.

---

## 5. What not to say

**Never in the tutorial.**

- Review and build vocabulary: gate, gate legs, leg 7, finding numbers (F1, F7, F11, F14 …), status-words rounds and
  item numbers, "the pending status-words PR".
- Commit hashes, PR numbers (#899 …), branch names, run ids, activity ids (`3ba02177` …), element GUIDs.
- "Proposal" as jargon. Say "a suggestion you can accept or reject", unless the screen word must be explained (below).
- Names of the marks ("half-moon", "dotted circle"). Show the mark and say what it means.
- "Declared measures", "declaration", "library step", "StepManifest", "entry point", "result kind", "absence
  sentence", "chat extent", "confidence form".
- Analysis ids as names: `fs_permissions`, `postgres_column_profile`, `db_catalogued`. Use what the screen calls them,
  or a plain description.
- Question ids (Q-0108) except in "Where to go next".
- "Classic", "/next", "the reset", "the throwaway", "8813" as a fact about the reader's setup.
- First names of anyone. "Owner decision" callouts belong in project records, not the tutorial.
- "The architect read…", "this walk did not press…". The tutorial is written for doing, not as a record of what a
  writer could check.

**Words the screen shows, and how to explain them.**

| Screen word | Where | Say |
|---|---|---|
| "EXPERIMENTAL UI" | sign-in panel | Leave unmentioned, or one line: the label on this version of the screen. (Gap G20.) |
| "Slug *" | register forms | The short name with no spaces used in addresses. |
| "resource" | everywhere | Means a data source. |
| "RFAs" | strip | "Requests for action": things a person must settle. |
| "ran via Prefect" | Survey & analyses | Leave unmentioned; it names the job runner. (Gap G16.) |
| "Scope: scouting" | Survey & analyses | The survey definitions shown are the ones for this stage. |
| "no reader yet" (◌) | Questions | There is no way to answer this automatically yet. |
| "answered automatically" | Questions key | Answered from what is already recorded, with no new check run. (Prose writer to confirm meaning.) |
| "a proposal · confirm it on Curate" | file-system survey | A suggestion found in the files; a person decides if it is right. |
| "derived" | file-system survey | Worked out from the folder walk Resource Explorer already made. |
| "unbound by reset" | Investigations | Its link to Egeria was lost when Egeria was reset; it can be linked again. |
| "zones: none · everyone visible" | Curate band | Anyone who can use this Egeria can see what you publish. |
| "kept survey" | Publish band | The latest survey Resource Explorer has stored, which the next press sends. |
| "◐ stale 9 of 12 steps …" | Publish band | Some results are older than their refresh rule; re-survey before publishing if you need them fresh. |
| "◐ behind" | Publish band | Egeria holds an older report than the kept one. |
| "From N stored results · …" | chat | The answer came from these stored results; the names after the dot are the analyses. |
| "Compile", "what would answer this?" | chat rail | A check of which analyses could answer your question and which have results. |
| "the eight intents" | Admin | Leave unmentioned. (Gap G19.) |
| "Ad-hoc" / "🏠 local" | new-investigation dialog / Investigations table | Two words for the same thing: kept in Resource Explorer only. (Gap G3.) |

---

## 6. Screenshots planned

None taken yet. Existing images from the merged walks are listed where one may be reused after a check that the screen
has not changed. Every screenshot is taken signed in as a tutorial user, not a developer account.

| # | Part · step | Screen | Shows | Reuse |
|---|---|---|---|---|
| S1 | 1 | Diagram, not a screenshot | Data source → survey → answers → your knowledge → curate → publish → Egeria | new |
| S2 | 2 · 1 | Sign-in panel | The panel, empty boxes | `01-sign-in-panel.webp` if unchanged |
| S3 | 2 · 3–6 | Whole screen, labelled | Strip, sidebar, main panel, chat rail, header, each numbered | new (labelled version of `01-stage-strip-and-sidebar.webp`) |
| S4 | 2 · 7 | Activity log | The latest entries and the filter buttons | new |
| S5 | 3 · 1 | Investigations page | The table and **+ New investigation** | `01-investigation-stage.webp` if unchanged |
| S6 | 3 · 2–6 | New investigation dialog | Filled in: name, purposes, kind Study, Ad-hoc | new |
| S7 | 3 · 8 | The investigation page after Make current | "Current investigation", header name, SCOPE · 0 | new |
| S8 | 4a · 1 | Find databases dialog | The three tabs and **Register one database…** | new |
| S9 | 4a · 3–4 | Register one database, filled | Fields filled, test passed, Register enabled | new |
| S10 | 4a · 5 | After Register | "It is in the database list now. Nothing was sent to Egeria." | new |
| S11 | 4a · 7 | The new database page | "add to <name>" then "already in <name>'s scope" | new |
| S12 | 4b · 2 | Add a file system | Path field with "✓ readable here" | new |
| S13 | 4c · 3 | Find repos, From a list | One row ticked, Import Selected | new |
| S14 | 4d | Sidebar filters | Filter box and chips | `01-repos-filter-chips.webp` if unchanged |
| S15 | 5 · 3–5 | Questions tab | Tabs, the count line, the key | new on a database |
| S16 | 5 · 5 | Marks table | One image of the key, or a drawn table | new |
| S17 | 5 · 6 | One question row, labelled | why is this here, answer, source line, buttons | new |
| S18 | 6 · 1 | Survey & analyses on a never-surveyed database | The start button | new |
| S19 | 6 · 2 | Running | "◔ running" and the notice with View | new |
| S20 | 6 · 3 | Questions after the survey | Answers filled in | new |
| S21 | 6 · note | Repository header tiles | Tiles incl. "? not read" | `02-scouting-questions-docling.webp` if unchanged |
| S22 | 6 · note | File-system survey | Reach line and counts | `04-folder-survey.webp` if unchanged |
| S23 | 7 · 1 | Discovery | "Nothing is recorded for this — a real absence…" | new |
| S24 | 7 · 3 | Analysis, a ○ row | "Nothing has been measured for this yet." | new on the database |
| S25 | 8 · 1–2 | Context tab | Sensitivity, Owner, Intended use set, signed and dated | new |
| S26 | 8 · 5 | RFAs drawer | One open item | new |
| S27 | 9 · 2–3 | Chat answer | The answer and the "From N stored results" line | new |
| S28 | 9 · 5 | what would answer this? | Analyses with and without results, **Run** | new |
| S29 | 10 · 2 | Contents, the chips | Three chips | new on the reader's database (`03-curate-database-chips.webp` is another database) |
| S30 | 10 · 3 | Include / Leave out | One of each | new |
| S31 | 10 · 4–6 | Findable and What people say | Tag, group, rating, "saved · will publish" | new |
| S31a | 10 · 7 | Repository Curate page | Its three tabs, labelled with the shared parts | new |
| S31b | 10 · 7 | File-system Curate page | Tags, group, "attaches the root folder only" | `05-curate-file-system.webp` if unchanged |
| S32 | 11 · 2 | Publish band before | "next publish" and **Publish** | new |
| S33 | 11 · 4 | Publish band after | "✓ in Egeria · … · confirmed" | new |
| S34 | 11 · 5 | Egeria reports | Report rows | `03-curate-publish-to-egeria.webp` if unchanged |
| S35 | 11 · 7 | Egeria Portal | The data source with the tag and survey report | new (depends on G17) |
| S36 | 12 · 2 | Select several | Three ticked, save as work list… | new |
| S37 | 12 · 4 | A work list | Rows × questions | new |

---

## 7. Gaps and screen defects

For the coordinator. Places where the app makes a step hard to explain, or shows confusing words. None is worked around
in this outline; each is named where it bites.

| # | Gap or defect | Where it bites | What would fix it, or what the writer needs |
|---|---|---|---|
| G1 | No named starter setup. The merged walks used whatever was loaded on the developer's server (`docling`, `coco_pharma`, `loading_bay`). A new reader cannot reproduce those screens. | all parts | A documented sample: which Egeria sample, which database, which folder, which repository. |
| G2 | The merged walks pressed nothing that writes, so every step that runs, saves or publishes was described, not shown. That is the main reason they "skip steps". The new tutorial must show survey, save and publish results. | 3, 4, 6, 8–12 | The owner's permission to press on a throwaway investigation and data sources, and to publish one to Egeria. |
| G3 | "Where it lives" defaults to "Create in Egeria", so a learner's first investigation writes to Egeria. "Ad-hoc" (dialog) and "🏠 local" (table) are two words for one thing. | 3 | Choose one word; consider Ad-hoc as the default. |
| G4 | No "start here" for a first survey. A never-surveyed data source offers several survey definitions and many **Run →** buttons; a file system offers seven start buttons (Survey, Measure beside Egeria's survey, Publish these measures to Egeria, Profile data files, Derive, Read narrative files, Match data classes) with no order. | 6 | A marked first action per kind, or a recommended order the tutorial can state. |
| G5 | File-system registration says "Mount (local path)" and "Canonical mount (blank = the mount)". The user guide says "host and container path". The survey then reports a different path, the one Egeria reads ("/deployments/loading-bay"). A reader cannot tell which path to type. | 4b | One explanation of the two paths, on the form. |
| G6 | "Slug *" is a required field on both register forms. Dashes are silently turned into underscores. | 4a, 4b | A plain label ("Short name"), or a hint under the box. |
| G7 | "Egeria connection (optional)" on the database form asks for "Egeria-visible host", "Egeria platform URL" and "View server". A data steward cannot know these. | 4a | Hide it from non-admins, or say when it is needed. |
| G8 | File-system survey says "a proposal · confirm it on Curate"; Curate says "Nothing to review for file systems yet." A dead end. | 6, 10 | Build the review, or remove the pointer. |
| G9 | Header can read "not signed in" while signed in (no investigation chosen). | 2 | Already queued as a defect. |
| G10 | Slow panes say "still loading" for 9–15 seconds without saying what they wait for (Discovery, Analysis, Enrichment). | 5, 7, 8 | Already queued as a defect. |
| G11 | A published database's header reads "never surveyed · not published to Egeria" while Curate says it is in Egeria; the sentence above the chips and a chip can disagree. | 4a, 10 | Already queued as defects. |
| G12 | "unbound by reset" is explained only by reference to an internal event. | 3 | A word that describes the state, not its history. |
| G13 | A ✓ beside an answer that says nothing could be checked ("not checked: 0 of 65 … could be queried"). | 5, 7 | Already queued as a defect. |
| G14 | The user guide says a database's Curate is one page; walk 3 shows tabs ("Describe and publish · Contents · Structure · …") on a database. One of them is out of date. | 10 | Read the screen and correct the guide. |
| G15 | "RFAs" is an unexplained abbreviation in the strip. | 8 | Spell it out on hover, or rename. |
| G16 | Internal words on screen: "ran via Prefect"; "compile" in the chat rail ("a compile reads one resource's stored results"); chat source lines list raw analysis ids ("fs_permissions, fs_activity"). | 6, 9 | Plain words, or analysis display names. |
| G17 | No single named place in Egeria for the reader to check that a publish arrived. | 11 | Name it (the Egeria Portal page, or a "Show in Egeria" link that opens Egeria itself). |
| G18 | Publish-band words a new user cannot read: "kept survey", "◐ behind · 76 annotations", "◐ stale 9 of 12 steps are stale", "◐ partly committed · 4 queued". | 11 | Plain sentences, or a hover that explains each. |
| G19 | The Admin dialog says "the eight intents"; the word appears nowhere else on screen. | Advanced tutorial | Say "the stages". |
| G20 | The sign-in panel says "EXPERIMENTAL UI". A new reader may doubt they are in the right place. | 2 | Remove, or explain. |
| G21 | This writer's browser was not signed in, so the register dialogs, the new-investigation dialog and the chat rail are outlined from the source code (marked "code"). | 3, 4, 9 | The prose writer reads each on the screen, signed in. |
| G22 | Steps whose exact screen words nobody has recorded: a wrong password, Egeria down at sign-in, an empty investigation name, an admin page refused, "promote" on a work list, the Assessment tab on a database, a step that asks before running a prerequisite. | 2, 3, 6, 7, 12, 13 | Read on the screen during the prose phase; some need a deliberate error to see. |

---

## 8. Decisions for the owner

| # | Decision | State |
|---|---|---|
| D1 | The main example data source | **Decided (project owner, 2026-10-29):** a database. Set the expectation that each kind's Curate page differs but the structure is the same, and show all three Curate pages (part 10, step 7). |
| D2 | The named sample setup | **Decided (project owner, 2026-10-29):** yes, one named sample. The Getting Started tutorial sets it up. Which database, folder and repository: still to choose. |
| D3 | Ad-hoc or "Create in Egeria" for the tutorial's investigation | **Decided (project owner, 2026-10-29):** Ad-hoc, described as the simplest starting point. |
| D4 | The first survey button for a database that has never been surveyed | Open. Find is the first action for bringing a data source in (part 4). D4 is the action after that, which starts its first survey. |
| D5 | Automate in the tutorial | **Decided (project owner, 2026-10-29):** no. Automate, extensibility and Admin go to an Advanced tutorial. Installing and configuring goes to a Getting Started tutorial. This is the Core tutorial. |
| D6 | Publishing during screenshots | Open, under discussion. |
