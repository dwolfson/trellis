# Declared extensibility, slice 2 (the Chat compile): what was built, choices, gaps (2026-10-28)

Companion to `DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE.md` (§3 the compile, §4 confidence) and to
slice 1's notes (`DECLARED-EXTENSIBILITY-SLICE1-PR1-GAPS.md`, `...-PR2-PUBLISH-TABLE.md`). The design PR (#821) named
three slices: declaration plus a generic renderer, the Chat compile, the publish table. Slice 1 shipped the
declaration and the publish table. This is the Chat compile. The Understanding renderer by result kind is still to
come; only `graph-renderer.js` exists.

## 1. Owner questions from slice 1 PR 1: answered

The project owner answered all four on 2026-10-28; the coordinator relayed them. They are recorded with their
words in `DECLARED-EXTENSIBILITY-SLICE1-PR1-GAPS.md` §3a. None is assumed.

| Question | Answer (project owner, 2026-10-28) | Built here |
|---|---|---|
| 1. `answers`: one list or two? | Generate them from the question catalogue's analysis_ids. | Generated on load. A hand-written list is refused, and the staleness check is a test. |
| 2. Should a not-built analysis declare? | Yes, marked "not built yet", so it reads as "planned, not measured". | `built: false` on the three stubs; Chat says "Planned, not built yet: not measured." |
| 3. Confidence per measure? | Yes, per measure; the headline is the weakest. | `MeasureDeclaration.confidence`, `confidence_of`, and the headline is refused unless it is the weakest. |
| 4. Repository analyses? | Declare them in the next slice and clear the four TODO markers. | Not here: that is slice 3. |

## 2. What was built

- **`resource_explorer/declared_context.py`.** One declared analysis's section, from its declaration alone.
  - The measures appear as `name: value unit (as of …)`. A member-scoped measure says its values are the rows.
    A measure with its own confidence adds its form (`· measured`), and the confidence line says it is the weakest.
  - Then comes the confidence line: the form, the basis or method, and for `inferred` whether the score is calibrated or a rule count.
  - Then each extent:
    - its declared fields only, in declared order;
    - FULL shows the declared rows and SUMMARY shows 3;
    - the truncation sentence, filled in when rows were left out;
    - at FULL, a `cite as:` line filled from the declared citation.
  - If an extent's rows are not in the result, the section says so; it never shows an empty list in their place.
- **`compile_context`.**
  - For an analysis whose catalogue entry declares itself, the compiler reads the fact. If it is known, the section is the declared one, replacing the generic flattening. The caveat still goes inside it, and the section counts toward the cap like any other.
  - A declared analysis that is not built yet is not read at all: it enters as planned, not measured.
  - If it is not known, the compiler takes the existing path, since findings may still say something. If that yields nothing, the analysis's declared absence sentence goes into the instructions section, after the coverage line. The manifest's gap entry gains `sentence` and `absence`.
  - After packing, any declared section the budget dropped or the cap deferred is named in a "Left out of this context" block, with its declared token cost. The block is added only if it fits the budget; otherwise it becomes a manifest note.
- **Manifest.**
  - `declared`: per packed section, the rung it went in at, the as-of, the form, and per extent and rung the total, the rows shown, and the identity of each row shown.
  - `confidence: {weakest, by_section}`.
  - `absences_in_context` and `omitted_in_context`.
  - `lists` now carries the declared extents, so the rail's "N of M" works unchanged.
- **Stored compile.** The recorded manifest carries `text`, which is what the model was given (§3.5). It is stored in the JSON column, so no DDL was needed. The manifest that is returned does not carry it.
- **Journal.** A turn's confidence words gain "rests at weakest on an <form> result (<sections>)". Compiles from before this slice read exactly as before.
- **The declaration.** An extent may declare `source`, the path or paths to its rows when they are not under its own name, and `tag`, the field naming which source a joined row came from. Twenty extents in the catalogue now declare a source. A tag that is not one of the extent's fields is refused.

## 3. Choices this slice made, beyond the note

1. **Absences ride in the instructions section, not in sections of their own.** The rail counts `packed` as "stored
   results used", and an absence is not a stored result. They appear at FULL and SUMMARY, at most 6 sentences with
   the rest named; the bare rung carries none.
2. **Order is the result's own.** A declared `order` is a sentence ("by row count, largest first"), not a sort key.
   The compiler takes rows in the order the reader returns them, and the sentence tells the model what that order is.
3. **Joined sources leave out the fields another source owns.** A row joined from several sources shows only the
   fields it carries; a field another source owns is not reported as `(none)`. For a single-source extent, a field
   the row lacks is said as `(none)`.
4. **Library steps are unwrapped once, by shape.** The shared reader wraps a step's record as `measurement_rows`
   (`name` and `properties`). The compiler unwraps it to the record the step declared (`scope` plus its properties),
   rather than each step's declaration learning RE's reader. The same mismatch probably affects the publish table's
   library-step value paths; see PR 2's note §3, last item.
5. **The instructions wording is unchanged.** Every instruction character is paid for in evidence (run 9), so no
   sentence was added to the A/B-tested instructions. The confidence line sits in each section, beside its numbers.
6. **Tokens are characters.** The packer budgets in characters. A declared `token_cost` is shown in the omission
   line and recorded in the manifest; it does not change how the packer budgets.

## 4. Gaps

- **`statistics_freshness.summary`.** Those rows are stored under the step key
  `statistics_freshness:statistics_freshness_summary`, and the attached reader does not return them, so the extent
  shows as "not in the stored result". The fix belongs in `survey_step_host` or `annotation_readers`.
- **No reader.** Seven declared analyses have no results reader: `nested_column_profile`, `sql_analysis`,
  `egeria_db_survey`, `resource_reachability`, and the three not built. They enter Chat only as their absence
  sentence, unless the findings table holds rows for them.
- **Rows, not row ids.** §3.5 asks for "the row ids behind each extent". Declared results come from readers, not
  from rows with ids, so the manifest records each shown row's identity: the values of its first two declared fields.
- **No live check.** Every compile in the tests reads a stubbed fact layer. No run against coco_pharma: the brief
  allows no writes to :5442, and a compile reads the registry there. The gate (§7) still needs the owner's walk.
- **The renderer.** The Understanding side of §2, a renderer per result kind, is the remaining half of slice 1.

## 5. Owner questions, with options

1. **Should absence sentences take budget ahead of evidence?** Today they ride in the required instructions
   section, and the barest rung drops them, so at a very tight budget the model loses them before it loses an
   evidence section.
   - (a) Keep as built: absences go first into the instructions, at FULL and SUMMARY only. *Recommended:* the
     barest rung is a last resort, reached only when nothing else fits.
   - (b) Put them in their own required section with a one-line floor ("nothing stored for: a, b"). This costs
     budget in every compile.
   - (c) Put them in an optional section with a high weight. That is cheaper, but an absence could be dropped
     silently, so a note is needed when it is.
2. **Should the declared `order` become a sort key?** Today it is a sentence.
   - (a) Keep it as a sentence and trust the reader's order. *Recommended for now:* no reader's order has been
     checked against its declaration yet, and (c) checks it without a second place to say the order.
   - (b) Add an optional `sort` field (`row_count desc`) that the compiler applies. This is exact, but it is a
     second place to say the order.
   - (c) Have a test compare the declared order with a live result per analysis. That needs stored results, so it
     belongs in the gate rather than in unit tests.
3. **Where does "judged" rank in the weakest link?** `CONFIDENCE_STRENGTH` puts it second, after measured.
   - (a) Leave it second: a person's verdict on the evidence outranks any estimate. *Recommended.*
   - (b) Rank it with inferred: a verdict is only as good as the evidence it saw.
   - (c) Do not rank it at all, and report a judged section beside the weakest link rather than in it.
