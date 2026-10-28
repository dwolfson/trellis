# Declared extensibility, slice 2 (the Chat compile): what was built, choices, gaps (2026-10-28)

Companion to `DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE.md` (§3 the compile, §4 confidence) and to
slice 1's notes (`DECLARED-EXTENSIBILITY-SLICE1-PR1-GAPS.md`, `...-PR2-PUBLISH-TABLE.md`). The design PR (#821) named
three slices: declaration plus a generic renderer, the Chat compile, the publish table. Slice 1 shipped the
declaration and the publish table. This is the Chat compile. The Understanding renderer by result kind is still to
come; only `graph-renderer.js` exists.

## 1. Owner questions from slice 1 PR 1, and their answers

The project owner's word, relayed by the coordinator on 2026-10-28: "I answered all the questions previously - we
should be able to move forward?" The table records where each answer was found, or what was assumed where none was.

| Question (PR 1 gaps §3) | Answer | Source |
|---|---|---|
| 1. Should a catalogue entry's `answers` be generated from the question catalogue? | **Assumed, owner to confirm:** no. They stay declared, and `test_analysis_declarations` holds them equal to the question catalogue's binding. The design's route step (§3.1) reads "the analyses that declare they answer it", so the declaration is the source. The compile still routes through the question catalogue, which the test keeps identical. | Design §1 (`answers[]` is a declared field) and §3.1. Nothing on generating them was found. |
| 2. Should a not-built analysis declare at all? | **Assumed, owner to confirm:** yes, as now. A not-built analysis is registered and listed (CLAUDE.md rule 17 names the three stub registrations), so it needs its absence sentence in Chat. Its value fields bind whoever builds it. | Rule 17. No ruling was found on declaring before building. |
| 3. Weakest link per declaration, or confidence per measure? | **Recorded:** a Chat answer reports the weakest link, never an average. It is now in each compile's manifest (`confidence.weakest`) and in the journal entry's confidence words. **Assumed, owner to confirm:** confidence stays one per declaration, not one per measure. | Design §4, "No aggregation into one number", from the owner's conversation with the architect on 2026-10-21. |
| 4. Repository analyses are not declared | **Recorded:** they are to be declared. `chaoss_metrics` declares the "top contributors by commit share, with names" extent. The Classic-view one-offs become declared users "by deleting code". **Assumed:** this slice does not declare them. The compile takes a declaration wherever one exists, so a repository analysis joins by declaring, and `_with_contributors` and its siblings retire then. | `REVIEW-QUESTIONS-AND-ANALYTICS-2026-10-22.md` addendum item 3. The architect's three-views ruling, 2026-10-21 (Architect Session). |

## 2. What was built

- **`resource_explorer/declared_context.py`.** One declared analysis's section, from its declaration alone.
  - The measures appear as `name: value unit (as of …)`. A member-scoped measure says its values are the rows.
  - Then comes the confidence line: the form, the basis or method, and for `inferred` whether the score is calibrated or a rule count.
  - Then each extent:
    - its declared fields only, in declared order;
    - FULL shows the declared rows and SUMMARY shows 3;
    - the truncation sentence, filled in when rows were left out;
    - at FULL, a `cite as:` line filled from the declared citation.
  - If an extent's rows are not in the result, the section says so; it never shows an empty list in their place.
- **`compile_context`.**
  - For an analysis whose catalogue entry declares itself, the compiler reads the fact. If it is known, the section is the declared one, replacing the generic flattening. The caveat still goes inside it, and the section counts toward the cap like any other.
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

## 5. Owner questions

1. Should absence sentences take budget ahead of evidence? Today they ride in the required instructions section
   and the bare rung drops them, so at a very tight budget the model loses them before it loses an evidence section.
2. Should the declared `order` become a sort key the compiler applies ("row_count desc") rather than a sentence? A
   reader that returns rows in another order today would contradict its own declaration without anyone noticing.
