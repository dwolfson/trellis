# Egeria/pyegeria blocker review — 2026-09-02

Read-only review. Source: `egeria-python/PYEGERIA_ISSUES.md` (canonical
tracker, read on this date), grep of this package for `ISSUE-`, and the
installed pyegeria version. RE's own `docs/egeria-pyegeria-issues.md` (6
entries, frozen 2026-08-06) was **not** used as a current source per its own
superseded notice — cross-checked only where the tracker references it.

**Installed pyegeria: 6.1.5** (`uv run python -c "import importlib.metadata as
m; print(m.version('pyegeria'))"`, from `packages/resource-explorer`; matches
`pyproject.toml`'s `pyegeria>=6.1.5`).

## Headline finding

As of this read, **the tracker records exactly two genuinely open issues**,
both Egeria-server-side, both in the "Open Egeria Server issues" section:
**ISSUE-79** and **ISSUE-38**. Everything under the tracker's "Open pyegeria
items" heading (ISSUE-82, ISSUE-81, ISSUE-80, ISSUE-78) carries a top-of-entry
`Status:` of fixed/resolved/not-a-bug as of 2026-08-28–30 — the file's own
section reorganization (moving them down into "Fixed / Resolved") evidently
hasn't been done yet, but the content says they're closed. Treat the section
heading as stale, not the entries. This is "the tracker says," not something
independently re-verified here (see Rules).

---

## 1. ISSUE-79 — native survey against a template-created `FileFolder` fails server-side (`assetConnector` null in `BasicFolderConnector.getFile()`)

**Status per tracker:** open, Egeria Server. Last touched 2026-08-30 (Egeria
team, Mandy Chessell): the original diagnosis ("template-created assets never
get a working `Connection`") is now **disproved** — 10/10 template-created
assets in the quickstart repo, and a fresh clean-archive build, both got a
real `ResourceConnection`. A new `files-fvt` suite runs the exact reported
scenario (template → catalog → native folder survey) and it **passes**,
asserting completion, not just that an engine action was produced. The NPE
itself is fixed into a named error (`OPEN-SURVEY-400-008`/`NO_ASSET_CONNECTOR`).
What's left unexplained is deployment-specific: which userId the engine
host's connector resolution ran as. The entry lists three concrete next steps
(re-run against a build with the NPE fix; check the asset's connection under
the actual engine-host userId; compare against `files-fvt` as a known-good
baseline) — none of which is something to run from here (no live-platform
testing per the task).

**Does it affect RE, and where?** Yes, directly — this is the blocker cited
by `docs/re-as-engine-host-plan.md` (still "ON HOLD" at the top, citing a
stale `ISSUE-51` number — not corrected to point at ISSUE-79; see
`docs/open-stack-checklist.md:150-175`, which already flagged the
renumbering mismatch on 2026-08-27/28) and by
`docs/repo-survey-catalog-completion-plan.md:7` and
`docs/end-to-end-gap-audit-2026-08-25.md:112,143`. Blocks cases 1/2/4 of the
engine-host design (anything needing a native Egeria survey to *complete*,
not just start) — case 3 (RE-local surveying) and case 4's already-verified
requester/poll code (`resource_explorer/surveyors/egeria_delegated_step.py`)
are unaffected by this specific bug, but a delegated step handing work to a
native folder/file survey would still hit it.

**Reproducible?** Tracker says the *original* symptom (NPE) was
last independently confirmed 2026-08-28, and the *underlying cause* has
since been reclassified — Egeria's own re-investigation says the premise
was wrong and a working end-to-end FVT now passes. Whether this specific
deployment's engine host would still hit it is explicitly unresolved in the
tracker itself ("what is left... needs the engine host that produced the
failure"). This is a case where the entry's own status is genuinely
in-between "still reproducing" and "fixed" — don't round it either way.

**Blocking severity:** **Blocks** — the direct, named holdup for
`docs/re-as-engine-host-plan.md` and the native-survey path of
`resource_explorer/surveyors/egeria_delegated_step.py` (its delegated-step
mechanics are built and live-verified independently of this bug, but a real
delegated survey against a template-created folder/file asset is still
exposed to it). Does not block database/filesystem *step authoring or
RE-local surveying* (case 3) — only the Egeria-orchestrated survey
validation work named in this task.

---

## 2. ISSUE-38 — `count_relationships_between_elements("Exception")` disagrees with `ClassificationExplorer.get_relationships("Exception")` by 1

**Status per tracker:** open, Egeria Server, explicitly held there by the
maintainer's own 2026-08-30 note pending re-verification against real data
(a `pushDown` query parameter now exists server-side; the entry stays open
until someone runs the three-part equality test the entry specifies, not
just on the strength of the code change).

**Does it affect RE, and where?** No RE code reference found (`grep -rn
"ISSUE-38"` across this package returns nothing). RE's own count/impact note
in the tracker is about `egeria-workspaces-fs`'s Overview dashboard, a
different app, not Resource Explorer.

**Reproducible?** Tracker's last direct re-check (2026-08-18) still showed
the byte-identical 58-vs-57 divergence for the `Exception` relationship
type only; the fix is server-side and released but its correctness is
explicitly unverified in the tracker as of 2026-08-30.

**Blocking severity for the work ahead:** **Irrelevant** to database/
filesystem resource types and to the engine-host/delegated-step validation
work — it's a relationship-count discrepancy on one relationship type, with
no RE code path depending on either counting method for those areas.

---

## 3. Recently-closed items worth knowing about (not open, but touch the areas in question)

Included because they were live "open" entries as recently as 2026-08-28-29
and directly concern the next-phase work; all now show a "fixed" top status
in the tracker as of 2026-08-30, but re-verification against a live server
was explicitly out of scope for this review.

- **ISSUE-54** (`findMetadataElements` on `Referenceable` silently
  incomplete/duplicated) — tracker status: fixed 2026-08-30, Egeria server
  commit `0d8d079c50` (missing unique tiebreaker in `ORDER BY`). The entry's
  own text flags this is proven on a 45-element test set, not the ~9,600
  element population the bug was originally measured against — "still to
  confirm" per the entry itself. No RE code reference found for ISSUE-54
  specifically, but broad-type scans of this shape are exactly the kind of
  query a filesystem/database catalog-discovery step could plausibly issue.
  **Degrades** database/filesystem work only if such a broad scan is used;
  irrelevant otherwise.
- **ISSUE-41** (`find_glossary_terms` classification filter + sequencing
  returns 0) — fixed 2026-08-30, same Egeria commit family. No RE reference
  found; unrelated to database/filesystem/engine-host work. **Irrelevant.**
- **ISSUE-78** (engine-host `claim`/`update_engine_action_status`/
  `get_active_claimed_engine_actions` missing from the released wheel) —
  resolved by pyegeria 6.1.5, the exact version installed here, and the
  tracker records RE's own upgrade + full suite + live smoke tests passing
  against it (2026-08-27). **Confirmed on this checkout's installed
  version** (6.1.5 ≥ the fix version) — the one item in this review where
  version comparison alone settles it. Directly enables the engine-host
  participation loop the survey-execution validation work depends on.
- **ISSUE-82** (`typeName=None` literal breaking 12 `ValidMetadataManager`
  methods) — fixed and released as **pyegeria 6.1.7**, newer than the 6.1.5
  installed here. Flagging the version gap, but **irrelevant to RE**: the
  only call site touching `ValidMetadataManager`
  (`resource_explorer/cli/main.py:1981-1982`, inside
  `_try_build_egeria_client`) only builds the client and fetches a bearer
  token — never calls any of the 12 affected methods. No action needed.

---

## Section 2 — the four unresolved governance-action-type questions

From `docs/extending-resource-explorer.md`, "Step elements, and the
implementation layer we do not model" (lines 283–341). Checking only whether
the tracker or RE's own code already contains evidence — not attempting to
answer these directly (another agent is doing that).

**1. Is the step→implementation link a first-class relationship
(`GovernanceActionProcessStep` → `GovernanceActionType`/
`GovernanceActionExecutor`), and what is it called?**

Partial evidence exists, but for a different edge than the question asks
about. `docs/re-as-engine-host-plan.md:44` records a source-verified chain:
`GovernanceActionProcessStep` → (`GovernanceActionExecutor{requestType}`) →
`GovernanceEngine` — i.e., a step links directly to an *engine*, not to a
`GovernanceActionType`. Separately, `Link Action to Action Executor`
(`ActionAuthor.link_governance_action_executor()`) was live-verified
2026-08-17 (same doc, and `docs/dr-egeria/re-delegated-step-probe.md`) as
linking a **`GovernanceActionType`** to its executor engine — confirming
that relationship exists and is named, but that's `GovernanceActionType` →
engine, not `ProcessStep` → `GovernanceActionType`. No tracker or RE
evidence found for a direct `ProcessStep`-to-`GovernanceActionType` link;
today's RE steps reference an implementation only informally, via
`additionalProperties.re_analysis_step`, per the question document itself.

**2. Does a `GovernanceActionType` carry the description, or does the
step?**

Tracker evidence bears on this, though it doesn't resolve it. **ISSUE-71**
(Dr.Egeria silently dropping `Produced Guards`, fixed 2026-08-21) shows that
`Implementation Description`, `Produced Guards`, `Wait Time`, and (for
Process Step only) `Ignore Multiple Triggers` are **all** declared on both
`Create Governance Action Type` and `Create Governance Action Process Step`
compact-spec commands, inherited from the same shared `Governance Action
Type Base` bundle (`commands_action_author.json`). So the schema lets
*both* element kinds carry a description independently — it doesn't force
"type is authoritative" or "step is authoritative." That ambiguity is
itself worth carrying into the other investigation: whoever answers this
should know the two element kinds aren't structurally distinguished on this
attribute today.

**3. Can a `GovernanceActionProcessStep` legitimately belong to more than
one process, independent of the above?**

No tracker or RE-code evidence found beyond what's already recorded in the
question document itself (Dan's own statement, quoted there). Not found:
any tracker entry discussing `NextGovernanceActionProcessStep` cardinality,
any RE doc independently confirming or measuring step reuse across
processes. This looks like a genuine gap — nothing already known here.

**4. Is `Guard` a runtime condition only, or can it carry structural
identity?**

Tracker evidence bears on this and suggests it's both, in different roles.
`re-as-engine-host-plan.md:44`'s confirmed chain shows guards used as a
**runtime routing condition** on `NextGovernanceActionProcessStep`
("guard-gated" chaining). Separately, **ISSUE-71** shows `Produced Guards`
is a **declared, structural vocabulary** attribute on the
`GovernanceActionType`/`ProcessStep` element itself — a list of outcome
names the step declares it's capable of producing, independent of any
specific run. `resource_explorer/step_outcome.py`'s outcome vocabulary
(referenced in ISSUE-71's "why it matters" note) is RE's own local mirror
of exactly this same idea. So there's tracker evidence that Guard already
operates in *both* senses Egeria's own model — a declared capability
(structural) and a chaining condition evaluated at runtime — which is
relevant context for whoever is resolving this, even though it doesn't
settle whether RE's model should treat them as one concept or two.
