# BRIEF — Files: the questions and analyses that finish the survey, so Classic can retire (2026-10-20)

From the design session at the owner's request ("we need to add more
questions and analyses to the Files surveys so we can finish that off and
retire the classic interface"). File system, never "file share".

## 1. Where Files stands

- **Questions.** Two of the 95 are the file system's own (Q-0094 what
  kinds of files and how much; Q-0095 recognisable tabular files), and
  Q-0011, Q-0056, Q-0066, Q-0069, Q-0070, Q-0080, Q-0081 and Q-0087 name
  `database;filesystem` but their answering analyses are database ones;
  on a file system most of them answer nothing today.
- **Analyses.** One registry step, `filesystem_inventory`
  (`surveyors/filesystem/survey_definition_adapter.py:301,335`), fed by
  `LocalFileSystemSurveyor` (walk: counts, bytes, extensions, formats,
  access/modify/create times, inaccessible paths; `_profile_data_files`:
  per-file column profiles for tabular files under a size limit, pandas
  required) and the hybrid and Egeria surveyors. File types already
  publish as Egeria's folder-survey annotations (file types note).
- **Classic-only screens** (parity note §3): register a file system with
  its Egeria fields (F-02), walk-and-survey modal (F-04, F-05), publish
  (F-06), reachability check (F-07), the survey report with metric cards
  and type breakdown (F-08), the per-file data profile accordion (F-09),
  and the Egeria reports list (F-10, partial). F-11 (run a definition) is
  present on /next.

- **Live state (read-only, 2026-10-20):** no file system is registered on
  8813 (`GET /api/filesystems/` is empty), so no survey rows, profiles or
  Egeria reports exist for any file system, and nothing can be gated on
  stored data today. The parity inventory of 2026-10-11 (`~/.re-gate/`,
  PI ids) has register (PI-022), per-row survey (PI-087), walk and profile
  (PI-091, partial), publish (PI-092), reachability (PI-093), the report
  (PI-094) and per-file profiles (PI-095) missing; list, remove, Egeria
  reports and run-a-definition done. The 10-11 hold ("file systems after
  Alpha") is superseded by the owner's 2026-10-20 decision to build the
  file-system block on /next before retiring Classic.

Classic retires when a person never needs it for a file system: register,
survey, read the answers, publish, and see what Egeria holds, all on
/next, with the questions answered from data the survey stores. Because
nothing is registered, the first slice is registration plus one walk on a
real local path, and every analysis below is gated on that walk's rows.

## 2. The questions to add (file system only, each with its analysis)

Numbered as proposals; the catalog assigns ids on the append.

| # | Question | Stage | Answering analysis | Stored today? |
|---|---|---|---|---|
| F1 | What is the shape of this file system: how deep, how wide, where does the bulk sit? | Scouting | `filesystem_inventory` (depth, breadth, the ten largest folders by bytes) | partly: totals yes, per-folder bytes and depth to add to the walk |
| F2 | What kinds of files are here, by count and by bytes, and which are data files? | Scouting | `filesystem_inventory` (formats summary, data-file classification) | yes (Q-0094) |
| F3 | Which tabular or structured files are here, with what columns and types? | Discovery | `file_profiles` (today's `_profile_data_files`, promoted to its own step so it can be run alone and priced) | yes, as part of inventory |
| F4 | Is this file system reachable by Egeria's engine host, or only locally? | Discovery | `resource_reachability` (built for Classic, F-07) | yes (Classic) |
| F5 | What has changed since the last walk: new, modified, removed files, and growth? | Discovery | `fs_change_rates` (two walks differenced on path, size and mtime) | no: needs the per-file rows kept per run |
| F6 | Which files are duplicates of each other, or of files in another registered file system? | Analysis | `fs_duplicates` (size plus content hash for files under a limit; cross-resource by hash) | no: hash column to add |
| F7 | Which files or folders contain personal or sensitive data? | Analysis | `data_class_match` on file profiles (reuses the database analysis over `file_profiles` columns, plus filename rules) | partly: data classes exist; profiles need the column rows kept |
| F8 | Which files has nobody touched for a long time, and which are hot? | Analysis | `fs_activity` (from access and modify times already walked; "can't tell" when atime is off) | yes, times are walked; the analysis is new |
| F9 | Who owns or can read what, and are there world-readable sensitive files? | Analysis | `fs_permissions` (owner, group, mode from stat; joined to F7) | no: stat fields to add to the walk |
| F10 | Does this file system contain a recognisable structure: a project, a dataset layout, an archive, backups? | Discovery | `fs_layout_signals` (README, manifest, schema files, dated folders, backup patterns) | no |
| F11 | What is the documentation inside it, and what does it say the contents are? | Discovery | reuse the repository docs ingestion over README and docs folders (the ingestion-rules note's "documentation shape") | no for file systems |
| F12 | How much would it cost to survey fully, and which parts are not worth it? | Discovery | the launcher's cost line from F1's bytes and file counts (the price-before-you-run rule, X-06) | partly |

Questions that already apply (`*` kinds) and need no new analysis on a
file system: Q-0002, Q-0003, Q-0005, Q-0012 (licence from a LICENSE file,
F10 supplies it), Q-0038, Q-0039, Q-0054 (becomes F4), Q-0055 (DataScope
from the mount's host and the walk's dates, the data-scope note).

Database questions that keep `filesystem` in their kinds but answer
nothing there today: Q-0011, Q-0056, Q-0069, Q-0070, Q-0081, Q-0087 lose
`filesystem` from their kinds until an analysis answers them on files;
Q-0066 (backups) stays, answered by F10's backup patterns plus the human
half; Q-0080 stays, answered by F7.

## 3. Analyses, in build order

1. **Walk extensions** (one step, one PR): per-folder bytes and depth,
   owner/group/mode, content hash under a size limit, per-file rows kept
   per run with a run id. These feed F1, F5, F6, F8, F9.
2. **`file_profiles` as its own step** with its cost line; column rows
   kept per run. Feeds F3, F7.
3. **`fs_change_rates`, `fs_duplicates`, `fs_activity`, `fs_permissions`**:
   four zero-fetch derived steps over the kept rows, each a library-style
   step with a nothing-to-derive guard ("one walk only", "no hashes",
   "access times not recorded on this mount", "no stat fields"), each
   publishing as Egeria's folder-survey annotation types where one fits
   (follow Egeria's lead: `ResourceMeasureAnnotation`,
   `ResourceProfileAnnotation`, `RequestForActionAnnotation` for a
   world-readable sensitive file).
4. **`fs_layout_signals`** and the docs ingestion reuse: F10, F11, and
   Q-0012's licence.
5. **`data_class_match` over file profiles**: F7, with the same
   proposal-only rule as databases.

## 4. The /next screens that retire Classic for files

Only what the parity rows name, in the Publish-ruling shape:

- Register a file system on /next (F-02, PI-022): slug, name, mount, canonical
  mount, group; the Egeria fields come from the platform configuration,
  never typed per resource.
- The survey press with its cost line (F-04, F-05) and the per-analysis
  run route for file systems (the 404 noted at F-05).
- The report on Understanding: At a glance (F1, F2 as the metric cards
  and treemap the multi-resource spec drew), Contents (the folder tree
  with the Include | Leave out selector and depth, the same module as
  databases, directories as parts), Over time (F5, F8).
- Data-file profiles (F-09) as rows under Contents, opened per file.
- Publish (F-06) through the same module: parts are directories, depth is
  folder then file, detail is the profile facets; Egeria's folder
  cataloguing as the lever; proof rows as everywhere.
- Reachability (F-07) as a line on the resource header, not a modal.
- Egeria reports list (F-10) as on databases.

## 5. Gate, by use

The owner registers a local file system on /next, runs the survey with
its price shown, reads F1 to F3 and F8 on Understanding, sees a flagged
world-readable file with a data-class match, publishes two directories
and reads them back in Egeria, and never opens Classic. A second walk
after adding and removing files shows F5 honestly.

## 6. Open for the owner

- [ ] Hash limit and whether cross-file-system duplicate detection is in
      the first slice.
- [ ] Which of F1 to F12 are Alpha; the rest follow.
- [ ] The CSV lister (file systems arrive hand-entered or by CSV today):
      in this brief or the discovery-sources one.
