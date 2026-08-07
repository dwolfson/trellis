# Using the Intent Shell

This is an end-user guide to Resource Explorer's web UI — what each part of the screen is for and how to use it. If you're extending or modifying the UI itself, see `CLAUDE.md`'s "Seven User Intents" section and `docs/survey-activity-design.md` instead; this document won't be kept in sync with internal implementation detail, only with what you see on screen.

## The shell, at a glance

```
┌─────────────────────────────────────────────────────────────────────┐
│  Resource Explorer          Activity   🔑 Connected as: ...   RFAs  Chat │  ← header
├─────────────────────────────────────────────────────────────────────┤
│ 🔭 Scouting  🔎 Discovery  ✅ Assessment  📈 Analysis  ✍️ Enrichment  │  ← intent nav
│ 📊 Understanding  🗂 Curate                                          │
├─────────────────────────────────────────────────────────────────────┤
│ Perspective:  DBA   Data Scientist   Steward   Security               │  ← perspective filter
├───────────────┬─────────────────────────────────┬─────────────────────┤
│  📁 Repos     │                                   │                     │
│  🗄 DBs       │        (content depends on        │    Chat panel       │
│  💾 FS        │         the active intent)        │  (always available, │
│               │                                   │   independent of    │
│  [resource    │                                   │   whichever intent  │
│   list]       │                                   │   is active)        │
└───────────────┴─────────────────────────────────┴─────────────────────┘
```

Three things stay independent of each other, and understanding that split makes the rest of the UI predictable:

1. **Intent** (top nav bar) — what you're trying to do right now. Exclusive-select: exactly one is active.
2. **Resource-type facet** (left sidebar: Repos / DBs / FS) — which kind of resource you're looking at. Also exclusive-select, but orthogonal to intent — every intent applies across all three resource types (with a couple of documented exceptions, noted below).
3. **Perspective** (the chip row under the intent nav) — who you are / what lens you're applying (DBA, Data Scientist, Steward, Security). This is **multi-select** — hold as many as apply to you at once. It's a filter, not a destination: it narrows what Assessment/Analysis show, it doesn't change what pane you're looking at.

Two more surfaces sit outside all of that, reachable from the header regardless of which intent/facet/perspective you have selected:

- **💬 Chat** — a persistent side panel for RAG-backed Q&A, scoped to whatever resource you have selected (or general if nothing's selected). Toggle it with the Chat button; it stays open across intent switches, and its collapsed/expanded state is remembered across reloads.
- **📝 RFAs** — a persistent drawer listing open RequestForAction items (things a survey found that need a human decision). Also stays open across intent switches. See its own section below.

## The seven intents

### 🔭 Scouting
Broad, fast inventory of a single selected resource — the survey report. Select a repo/database/filesystem in the sidebar to see it; Scouting reads its content from whichever resource-type facet is active. If nothing's selected, you'll see a prompt to pick one.

### 🔎 Discovery
Egeria's own Survey Definitions for the selected resource — the most Egeria-native way to launch a survey, showing exactly what steps a Survey Definition runs and where each step executes (locally in Resource Explorer, or natively in Egeria).

### ✅ Assessment
Scored evaluation of the selected resource against criteria — things like Security Scan, Documentation Coverage, Index Health, Privilege Audit. Each card shows what it produces, how fast it runs, and whether it's a local or Egeria-native analysis. Filter the list further with the Perspective chips. A ⚠ note appears if Resource Explorer couldn't reach Egeria to merge in its native analyses — the list you see is still complete for locally-known analyses, it just may be missing Egeria's.

### 📈 Analysis
Structural and quantitative work that isn't a scored evaluation — dependency scans, data profiling, API/symbol extraction. Same card layout and Perspective filtering as Assessment; the distinction is purely about what kind of work each entry represents.

### ✍️ Enrichment
The Context form — record facts about a resource that can't be derived from scanning it: environment (production/staging/dev), sensitivity, responsible steward, org owner, backup status, purpose, notes. Fields marked ★ required generate an open RFA if left blank, so leaving something blank isn't silently ignored — it shows up in the RFA drawer as something to follow up on.

### 📊 Understanding
Charts — stars/commits/languages/health/file types for repos, schema/table/column/history charts for databases. Select a resource, then use the chart-type tabs above the chart to switch what's plotted. Filesystem charts aren't built yet; you'll see an honest note rather than a blank panel if you're on the Filesystems facet here.

### 🗂 Curate
Catalog maintenance, not resource-specific — this intent has its own sub-navigation (a small tab strip: Annotation Types / Groups / Schedules) rather than reacting to the sidebar selection or facet.
- **Annotation Types** — the registry of metadata annotation schemas: what each one means, what properties it carries, and its mapping to Egeria's own property classes. Register, edit, or delete entries here.
- **Groups** — group related repos/databases/filesystems together (e.g. everything belonging to one product). Create and delete groups here; assigning an individual resource to a group is done from that resource's own record, not from this list.
- **Schedules** — set a recurring cadence (daily/weekly/monthly) for a selected resource's analyses, and enable/disable them individually. **Read the caveat shown at the top of this pane** — not every listed analysis is fully implemented yet; cross-check against Discovery's Survey Definitions before relying on a scheduled run actually doing what its name suggests.

## The RFA drawer

Click **📝 RFAs** in the header to open it. It lists open RequestForAction items — things a survey or the Context form flagged as needing a human answer — grouped by resource, with a badge on the header button showing how many are currently open.

Each item has three response actions, plus a free-text answer field:

- **⏸ Defer** — pick a date to revisit it later. It drops out of the default (open-only) view until then.
- **👤 Reassign** — hand it to someone else by name or email.
- **✓ Complete** — mark it resolved, optionally with a note explaining the resolution.
- **↺ Reopen** — bring a deferred/reassigned/completed item back to open, if needed.
- **✏ Record answer** — a free-text box for capturing the actual answer to whatever the RFA is asking, independent of its response-action status.

Check **Show resolved** at the top of the drawer to see deferred/reassigned/completed items alongside the open ones — they're hidden by default so the drawer reflects what still needs attention, not the full history.

**One thing this doesn't do yet:** none of these response actions write back to Egeria as a native `ToDo` or governance action, or update the RFA's own properties there. They're recorded locally in Resource Explorer only. If your workflow depends on Egeria itself reflecting an RFA's status, that's not there yet — track it separately for now.

## Tips

- **Column widths are resizable.** Drag the thin divider between the sidebar and main content, or between the main content and the chat panel / RFA drawer, to resize. Your chosen widths are remembered across reloads.
- **The feedback button** (bottom-right, 💬 Feedback) is draggable if it's ever in your way — click and drag it anywhere on screen; its new position is remembered.
- **"Connected as" in the header** shows which Egeria service account Resource Explorer is using — it's informational, not a login control. There's no per-user login yet; the account is configured once via `.env` (`EGERIA_USER_ID`/`EGERIA_USER_PASSWORD`), not from the UI. Click the badge for a reminder of this.
