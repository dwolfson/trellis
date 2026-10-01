# DESIGN — Find and Integrate purposes, and the data lens on the investigation (2026-09-30)

**Status: design, discussion closed for a first slicing; nothing built.** From the
design session with the project owner, 2026-09-30. Sits on
`investigation-framing-design.md` (purposes; "ranks, never excludes"),
`multi-resource-questions-design.md` §16 (the free estimates and preliminary fit),
`DESIGN-BROADER-QUESTIONS-WITHOUT-CONTENT-INGESTION.md` (similarity without ingesting
content) and `REPLY-DESIGNER-ENRICHMENT-STAGE-IA.md` (the lens belongs to the
investigation). Egeria reference: the DataLens concept
(https://egeria-project.org/concepts/data-lens/).

## 0. Decisions

**Decision (project owner, 2026-09-30):** two purposes join the vocabulary: **Find**
and **Integrate**. "Discovery" was the working name for the first; it was renamed
because Discovery is a canonical stage (`CLAUDE.md` rule 17) and a purpose with the
same word would appear on the Discovery tab. "Match" was considered and kept as the
verb on rows ("matched against the lens on 4 of 6 dimensions"), not as the purpose.

**Decision (project owner, 2026-09-30):** an investigation can carry **a specification
of what it is looking for**. Nothing on screen holds that today. The specification is
Egeria's **DataLens**, stored locally first, with named things (subject terms, data
classes) added to its dimensions.

**Decision (design session, 2026-09-30):** purposes keep the rule that they rank and
never exclude. A purpose adds questions by tagging them. A question that cannot be
answered without a lens, or without a second resource in scope, says so on its row as
a precondition; it is never hidden.

## 1. The one idea

A resource has an **offer**: what it holds, at what grain, over what time, about which
subjects, in whose custody, under what terms. An investigation has an **ask**: the same
dimensions, as requirements. **Find** is ranking offers against one ask. **Integrate**
is comparing offers with each other, under the same ask. Everything below is which
dimensions each side can fill in, and how honestly.

```
resource ──measure──▶ offer ─┐
                              ├── match by dimension ──▶ fit (Find) / compatibility (Integrate)
investigation ──declare──▶ ask ┘      │
                                      └── absent dimension → "not measured", never a zero
```

## 2. The two purposes

### 2.1 Find

*Why this work exists:* to locate resources that satisfy a stated requirement, without
cataloguing everything seen on the way.

The Coco scenario (§7) is the model: an acquiring company looks through many unfamiliar
systems for the best, most current sales, HazMat or manufacturing data, and most of what
it finds is irrelevant or archival. Find's flow is Scouting across all candidates at
inventory cost, then ranking by fit against the lens, then cataloguing and publishing
only what is chosen. The investigation's per-resource verdicts give the outcome a home
(adopt, archive, ignore), and RE's local-first storage means an unchosen database costs
nothing in Egeria.

Questions Find adds or promotes (tagged `Find`): "does this resource hold data about
*subject*?", "how current is it, and is anything still writing to it?", "what time range
and grain does it cover?", "whose is it?", "under what terms may it be used?", and the
fit question itself, "could this be in scope for what I am looking for?" The last is
`preliminary_fit`, today locked behind a lens that cannot be declared (§4).

### 2.2 Integrate

*Why this work exists:* to learn how resources fit together, or how a candidate can be
used with resources already catalogued.

Integrate has two steps, and the first stands alone:

1. **Describe the offer, per resource, and advertise it.** Today's integration view of a
   repository is its interface surface, which the owner called "quite inadequate": it
   should cover protocols and formats spoken, events emitted and consumed, data expected
   and produced, and the subjects the software is about. For a database the offer is
   data classes per column, identifiers and keys, grain, time coverage, currency and
   subject terms. Most of this reads from stored survey rows (Discovery tier in the
   CLAUDE.md rule 17 sense); data-class derivation from column profiles is the new
   reader. **Advertising** is a publish step writing the measured offer to Egeria as a
   **DataScope** classification on the asset, which is exactly what a DataLens matches
   against (§3). Semantic assignment of glossary terms and logical-schema matching
   against schemas Egeria already knows are judgements a person confirms, so they belong
   in **Curate** (§6), and may outgrow RE into a tool of their own.

2. **Compare offers.** Integration questions are about a pair, or about one resource
   relative to the investigation's set: shared identifiers, compatible grain and time
   coverage, overlapping reference data, vocabulary agreement, format compatibility. The
   catalogue cannot express a question whose subject is "this resource against the
   others in scope" yet; that is a new question shape (§5.3). Comparison has a
   precondition the owner named: **knowledge parity**. Both resources must have the same
   analyses run at comparable depth, or the row says "can't compare yet: *X* lacks column
   profiles" and names what to run. Parity is measured from step rows, so the word on
   the row has proof behind it.

Integrate does not do mapping or transformation. Deciding how one schema maps onto
another, and building the transformation, is downstream of knowing the two offers, and
is a different tool's work (Egeria's lineage and data-processing models are the
catalogue of record for it). RE's role ends at: these two resources are comparable, here
is where they agree and differ, dimension by dimension.

## 3. The data lens

### 3.1 What it is, and what it is not

Egeria's DataLens (model 0430) "establishes the scope of data needed for a business
capability or project" across subject, location, time, organisation, quality and
regulatory dimensions, and is most effective when it "lists the identities of the open
metadata elements" rather than literal values. The owner co-designed it; what it lacks
for Find is **specific names of things**: Sales, HazMat, Manufacturing, as terms a
search can use.

`investigation-framing-design.md` dissolved a "Lens" *axis* on 2026-08-24 because its
members were purposes and perspectives in disguise. This is not that. The data lens is a
**declared object attached to one investigation**, not a vocabulary for tagging
questions. `curation-lenses-design.md` uses "lens" for a *cut* over recovered
architecture; to keep the two apart on screen and in code this object is always the
**data lens** (`data_lens`), never bare "lens".

### 3.2 Dimensions

Each dimension holds a literal, or a reference to an Egeria element, or nothing, and the
row says which. References are preferred; literals are allowed so a lens can be declared
before Egeria has the element.

| dimension | literal form | Egeria reference | matched against (resource side) |
|---|---|---|---|
| subject | terms ("Sales", "HazMat") | GlossaryTerm, DataClass, SubjectArea | `subject_signals` terms, via glossary synonyms; `data_class_match` |
| data classes | names | DataClass | `data_class_match` |
| location | names | Location | owner/organisation observations; no reader yet |
| organisation | team or unit | Team, BusinessCapability | observations on Context; `datdba` owner role |
| time | range | ContextEvent, DataScope | time coverage from date columns (new reader) |
| grain | statement | DataGrain | `grain_determination` |
| currency | "updated within *n* days", "still written to" | — | `db_activity_signals`, max-date columns, archive signals (new reader) |
| quality | thresholds | CertificationType | profile completeness (`coverage_signals`, column profiles) |
| terms | licence or certification | LicenseType, CertificationType | licence observation (E3) |

The subject dimension is where the names live. A term typed on the lens is looked up in
the glossary; a term with no glossary entry is kept as a literal and the row says "not in
the glossary". Matching a resource's derived subject signals against the lens goes
through the glossary too, so "Sales" finds "orders", "invoices" and "customers" because
the glossary says they are related, never by string.

### 3.3 Storage and Egeria

Local first, nullable Egeria GUID, the same pattern investigations use: an
investigation owns at most one `data_lens` row holding the dimensions as JSON, each
dimension carrying `{literal, egeria_guid, egeria_type}`. Publishing the investigation
publishes the lens as a DataLens element, `GovernedBy` the investigation's resource
collection, and fills the GUID in. Nothing about the lens requires Egeria to exist.

### 3.4 On screen

The investigation page gains a section, "what we're looking for", listing the
dimensions as rows with the shared row anatomy: value, literal-or-reference mark,
who declared it and when. Context's existing "declare it on the investigation ›" link,
shipped in E1 as a not-built affordance, points here. The ad-hoc "try one on this
resource only" (`lens_source: ad_hoc`) stays deferred until the declared form works.
Where the section sits on the investigation page is for the designer (§8).

## 4. Fit by dimension

`preliminary_fit` becomes real: a resource measured against the data lens, one row per
dimension, four states kept distinct as its catalogue entry already requires: **fits**,
**does not fit**, **could not check** (the resource-side input is itself not
established), and **not measured** (no reader exists for this dimension on this kind).
The headline is a count, "matched on 4 of 6 dimensions · 2 not measured", never a score
that hides silence. Find orders candidates by matched dimensions, then by currency,
and shows the count beside each.

## 5. What has to be built

### 5.1 Readers on the resource side

- **Data classes per column** from column profiles and bounded sampling:
  `data_class_match` exists (queued, api_heavy); the offer reads its annotations.
- **Time coverage**: min and max of date and timestamp columns per table, from the
  profile where it exists, else a bounded query; new reader.
- **Currency and archive signals**: last modification activity, whether any role has
  write access and uses it, max-date drift against now; extends `db_activity_signals`
  (already queued in the database-analysis batch). "Probably an archive" is a finding
  with its evidence, never a verdict.
- **Repository offer**: protocols, formats, events, data in and out, subjects; extends
  `interface_surface` and `api_structure`, plus a `subject_signals` for repositories
  over README and documentation terms, which the RAG ingestion already embeds.

### 5.2 The ask side

The `data_lens` table, its routes, the investigation-page section, glossary lookup for
subject terms, publish as DataLens.

### 5.3 Relational questions

A question whose subject is a pair. The CSV gains a `subject_shape` column with values
`resource` (today's default) and `pair`; a pair question renders only inside an
investigation, once per unordered pair in scope, with the parity precondition on each
row. Compilers that assume one resource per question skip pair questions and say so.

### 5.4 Advertising

A publish step writing the measured offer as a DataScope classification on the asset,
with the same proof rule as every publish: the row says "advertised · *time*" only with
the classification read back.

## 6. The Curate boundary

Semantic assignment (glossary term to column or table) and matching a physical schema
to a logical schema Egeria knows are judgements. They start from the measured offer and
end in a person confirming; they belong in Curate with the four observation states from
E3 (proposed, confirmed, overridden, survey-now-disagrees). If the schema-matching work
grows past what a Curate tab can hold, it becomes its own tool reading the same offers;
nothing here forecloses that.

## 7. Demo scenarios

Two scenarios, one corpus.

**Acquisitions.** Coco Pharmaceuticals merges with acquired companies and looks through
their systems for the best, most current sales, HazMat and manufacturing data to
integrate with Coco's own. Most systems are archives or irrelevant. Find with a lens;
catalogue only what is chosen. AdventureWorks, already registered, is sales data and can
play one acquired system.

**Regional sales forecasting.** Coco's pre-existing regions each run their own sales
forecasting system; the acquisitions add more. The goal is one integrated forecast.
RE's role: find each region's forecasting data, describe each offer, measure parity and
compatibility, and hand two comparable offers to the mapping and transformation work
that follows (outside RE).

**Decision (project owner, 2026-09-30):** the pre-existing regional systems will be
created as databases with synthetic data. The corpus is therefore a design artefact
too. Each regional database should differ from the others on purpose, so that every
lens dimension and every integration question has a case that exercises it:

- different schema shapes for the same facts (star vs flat; forecast by month vs by
  week), to exercise grain and structural similarity;
- different naming conventions and comment coverage, to exercise subject signals and
  the glossary path;
- different time coverage and currency: one region current, one stale, one an obvious
  archive with no writes;
- different currencies, units and regional calendars, to give the mapping work real
  differences to map;
- at least one PII-bearing table, to exercise data-class matching and the terms
  dimension;
- different owner roles and licences, to exercise organisation and terms.

A corpus whose databases differ only in data values would make every match trivially
pass and prove nothing. The differences are the demo.

## 8. For the designer

The pending `ASK-DESIGNER-WORK-LISTS-VS-INVESTIGATIONS.md` (#354) already asks what the
investigation page is. The data lens section, the purposes on the investigation, and
Find's ranked candidate view belong on that same page, so they go into the same round
rather than a second one. The ask needs an addendum: the lens rows, the "matched on *n*
of *m*" headline on a candidate, the verdict controls beside it, and how a pair question
is drawn.

## 9. Slicing

In order, each with an owner gate on 8813, both databases plus the synthetic regions
once they exist:

1. **Purposes.** Add Find and Integrate to `VALID_PURPOSES` and the catalogue's purpose
   column; reconcile the registry list with the design doc's seed table (Remediate and
   Attest are in the table and the CSV, not in the code). Tag the questions in §2.1.
2. **Data lens record and page section**, literal values first, glossary lookup for
   subject terms, Context's link pointed at it.
3. **Fit by dimension**: `preliminary_fit` unlocked, four states, the count headline;
   Find's ranked view.
4. **Resource-side readers**: time coverage, currency and archive signals, repository
   subjects.
5. **Advertising** as DataScope on publish, with read-back.
6. **Pair questions and parity**, the first Integrate questions.
7. **Curate**: semantic assignment and schema matching as proposed-then-confirmed rows.

Slices 1 to 3 need no new survey fetch and can start once the designer answers §8.

## 10. Open questions

- Which glossary is the subject vocabulary for a tenant with several? Default to the
  one the investigation's Egeria project is governed by; otherwise ask.
- Does a lens belong to one investigation, or can several investigations share one?
  Egeria allows sharing; the first slice gives each investigation its own and the
  question stays open until a second investigation wants the same lens.
- The ad-hoc per-resource lens (`lens_source: ad_hoc`) is deferred, not dropped.
- Whether "currency" is a lens dimension or a ranking preference. Here it is both: a
  threshold on the lens when declared, a tie-breaker in Find's ordering otherwise.
