# The interface ladder's missing rung is a missing *fact*

**Subject:** `interface_surface`'s `implemented` rung for `http_api`, `grpc`,
`graphql`, `messaging`, `soap`
**Read against:** `resource_explorer/surveyors/sub_surveyors/interface_surface.py`
at HEAD, after `#103`
**Answers:** `SPEC-ACTIONABLE-AND-HONEST.md` §6, and the `Open:` note on
`docs/dr-egeria/resource_questions.csv`'s *What are the public interfaces?* row
**Status:** design only. No code in this change.

---

## The one-paragraph version

`#103` gave `cli` a path to `implemented` by **reading a fact another walk had
already stored** — `deployment_evidence`'s `dunder_main` evidence. The five
route-like kinds have no such path because **no step in this pipeline stores the
equivalent fact.** `project_code_symbols` records symbol *definitions* only: no
decorators, no annotations, no import statements, no call or registration sites.
That single omission is why `interface_surface` reports `could_not_check` for
`http_api` *and* why `egeria_interfaces` can only ever produce a lower bound
(its own `basis_note` says so in as many words). So the work is not to design a
rung — the rung exists and is correctly wired. The work is to **capture the
fact**, in the one step that is already parsing every source file with a real
AST, and then to read it from `interface_surface` exactly the way `#103` reads
`dunder_main`. A design that specified the rung without specifying the capture
would produce a spec nothing can implement.

**Recommendation:** extend `CodeSymbolExtractor` to record decorator/annotation
registrations into a new `project_code_markers` table, written by
`repo_symbol_extraction` (which already downloads the zipball and already walks
every AST node, so the marginal cost is a list traversal per function).
`interface_surface` stays Discovery-tier and stays zero-fetch — it gains a
**fourth stored-row input**, not a fetch. Do **not** invent path-only heuristics.
Do **not** make the catalog row `MIXED:`.

---

## 1 · Is an honest zero-fetch detection possible from what is stored today?

Three candidate sources were checked against the code rather than assumed.

### 1a · Path-only patterns (`routes.py`, `api.py`, `controllers/`) — **no**

This is the tempting one, because it looks like the `dunder_main` precedent. It
is not the same thing, and the difference is the whole of this project's
honesty position.

`__main__.py` is not a naming convention. It is a **language-defined contract**:
CPython executes exactly that file, by that name, when the package is run with
`-m`. A path-only check for it is a statement about what the interpreter will
do. There is no judgement in it and nothing to get wrong beyond the path itself
— which is why `deployment_evidence.classify_distribution` can compute it from
`project_file_inventory` with no content read and still call it evidence.

`routes.py` has no such property. Nothing executes it because of its name. A
repository may serve 400 routes from `app.py`, or ship a `routes.py` that
defines a frozen constant list, or carry a `api/` directory that is a *client*
for somebody else's API — which is the exact inversion, and it is common. The
module docstring already names this failure mode: *"a fact known by one walk and
not read by another, producing a confident sentence the repository itself
contradicts."* A filename-derived `implemented` would be worse than that: a
confident sentence with **no** walk behind it at all, dressed in the vocabulary
of one. It would also silently promote every `implied` finding one rung, since
the repos that depend on `fastapi` are overwhelmingly the repos that have a file
with `api` in its name.

If such a signal were ever wanted it belongs on the `implied` rung as a second
weak corroborator, never on `implemented`. It is not recommended at all.

### 1b · `architecture_interfaces` port findings — **partially yes, and free**

This is the genuinely useful discovery, and it was not in the brief.

`arch_recovery` **already counts FastAPI route decorators and already stores the
count.** `arch_recovery/code_markers.py` runs an ast-grep rule
`fastapi-route-registration` (`rules/fastapi-route.yml`); `propose()` returns
`code_marker_operations` as `{component slug: route count}`;
`arch_recovery/interfaces.py:543` turns that into a port with
`protocol="HTTP/REST"` and `operation_count=n_routes` and the literal detail
string *"FastAPI route decorators observed in code (ast-grep) — N route(s); no
OpenAPI document present"*; and `arch_recovery/persist.py:_persist_interfaces`
writes it as a finding under kind `architecture_interfaces`.

So for FastAPI specifically, `SPEC-ACTIONABLE-AND-HONEST.md` §6's worked example
— *31 FastAPI routes across 4 modules* — is **already computed and already in
the database**, on any repo where `repo_arch_detect` has run. `interface_surface`
does not read it.

Reading it is zero-fetch by the same argument `#103` used: `query_findings(slug,
"architecture_interfaces")` is a second READ of a table another step wrote, not
a second parse and not a second fetch. The docstring's current objection — *"that
walk fetches a fresh zipball and is not Discovery-tier, so its output is not a
fact this zero-fetch analysis may read"* — **proves too much.** By that argument
`interface_surface` may not read `distribution` either, since `repo_manifest_parse`
fetches; and it does read it, correctly, because the tier constraint is on *this
step's own cost*, not on the provenance of rows it finds already written. The
objection should be replaced with the real constraint: a stored row may be read,
and its **absence must never be read as a zero**.

The limits are real and must travel with the finding:

- **FastAPI only.** `MARKER_ROLES` carries `fastapi-route-registration`,
  `go-http-server`, `go-grpc-server`, `java-spring-service`, `typer-cli-…`,
  `textual-app-subclass`, `scheduler-worker` — but only FastAPI's count is
  threaded through to `code_marker_operations`. Flask, Django, Starlette,
  Express, Axum, Spring MVC route counts do not exist.
- **Component-attributed, and lossy.** `interfaces.py` deliberately skips any
  route count whose component has no resolvable name, and suppresses the port
  entirely when a static OpenAPI document already covers that component. Both
  are right for the architecture view and both mean the count is not a
  repository-level total.
- **Requires `repo_arch_detect` to have run**, which is Analysis-tier and
  `availability: queued`. On most repos at Discovery time it has not.

That makes 1b a **real but partial** answer: worth shipping, insufficient alone.

### 1c · `project_code_symbols` — **no, and this is the root cause**

`CodeSymbolExtractor` and its four language backends produce `CodeSymbol`, whose
fields are: `kind`, `name`, `qualified_name`, `signature`, `docstring`,
`start_line`, `end_line`, `parent_class`, `return_type`, `is_private`,
`is_async`, `complexity`, `bases`. The table (`registry.py:1534`) mirrors them.

There is **no decorator field, no annotation field, no import record, and no
call/registration site** — and `_PythonVisitor._make_func` reads
`node.returns`, `node.args` and `ast.get_docstring(node)` off an AST node whose
`decorator_list` is sitting right there, unread.

This is the same omission `egeria_interfaces` documents from the other side. Its
`basis_note` is explicit: *"project_code_symbols records only symbol DEFINITIONS
(no import statements, no call/instantiation sites)"*, and its findings are
capped at `confidence: 60` *"never higher: … this is a lower bound"*. Two
analyses, one missing fact. That is the strongest argument that the fix belongs
in the capture layer and not in either consumer.

---

## 2 · Is `could_not_check` the permanent answer? **No — and it should not become someone else's problem either**

`could_not_check` is the *correct* answer **today**, and `#103`'s decision to say
so rather than guess `implied` should not be revisited. But it is a finding about
the analysis, not about the repository — `SPEC-ACTIONABLE-AND-HONEST.md` §3's
**ours** destination — and a permanent **ours** is a gap nobody ever closes.

Deferring it to `api_structure` does not work. `api_structure` extracts nothing;
it reads `project_code_symbols`, and that table lacks the fact. Pointing the
question at a later tier would move the sentence without moving the capability,
and would leave a second analysis reporting a lower bound with no note saying
why. The tier is not the obstacle. The **schema** is.

**So: keep the question at Discovery, keep `interface_surface` as its single
answering analysis, and fix the capture.** The tier argument survives intact
because `interface_surface` still fetches nothing — it reads a row a fetching
step wrote, which is precisely the shape `#103` established and which the
`distribution` input already relies on.

---

## 3 · The recommended change, named concretely

### 3.1 · Capture — a new table, written by `repo_symbol_extraction`

**New table `project_code_markers`** (`registry.py`, beside
`project_code_symbols` / `project_code_relationships`):

| column | meaning |
|---|---|
| `project_slug` | as everywhere |
| `file_path`, `start_line` | where the registration is |
| `language` | so an unsupported language is distinguishable from a clean one |
| `marker_kind` | `route` \| `rpc_method` \| `resolver` \| `message_handler` \| `soap_operation` |
| `framework` | `fastapi`, `flask`, `django`, `starlette`, `express`, `spring-mvc`, `grpc`, `strawberry`, `celery`, `kafka` … |
| `interface_kind` | the `interface_surface` kind this proves: `http_api`, `grpc`, `graphql`, `messaging`, `soap` |
| `detail` | verb/path where the decorator carries them (`GET /assets/{guid}`), else `''` |
| `qualified_name` | the decorated symbol, so it joins back to `project_code_symbols` |

**A separate table, not columns on `project_code_symbols`** — recommended, for a
mechanical reason: that table's key is `UNIQUE(project_slug, file_path,
qualified_name)`, one row per symbol, and a single handler can carry several
registrations (`@app.get(...)` and `@app.post(...)` on one function is ordinary
FastAPI). Columns would force a lossy flattening on day one. A marker is also
not a symbol: it is a *fact about* a symbol, the same relationship
`project_code_relationships` already models with its own table.

**Written by `repo_symbol_extraction`** (`SymbolExtractionSurveyor`,
`StepInfo` at `repo_survey_definition_adapter.py:982`), extending its `produces=`
tuple to `("project_code_symbols", "project_code_relationships",
"project_code_markers")`. This step already declares
`requires_resources={"zipball_root": "local_path"}` and `fetch_cost="download"`,
already reads every first-party source file, and already parses it. **The
marginal cost of the capture is walking `node.decorator_list` on nodes the
visitor has already constructed** — no new fetch, no new parse, no new
dependency. `compute_cost` stays `medium`.

**Per-language capability must be declared, not implied.** Python via
`ast.decorator_list` is exact and free. Java via the existing tree-sitter grammar
(`@GetMapping`, `@RequestMapping`, `@KafkaListener`) is real work but tractable.
JS/TS and Go have no decorator equivalent for the common frameworks — Express
registers by method call, Go by `mux.HandleFunc` — and honestly need call-site
capture, which is a larger change. Follow the precedent already in the codebase:
`api_structure.py`'s `_COMPLEXITY_CAPABLE_LANGUAGES` and `documentation.py`'s
`_DOCSTRING_CAPABLE_LANGUAGES` exist because a stored `0` from a language nobody
measured is indistinguishable from a measured zero. Add
`_MARKER_CAPABLE_LANGUAGES` and name the excluded languages in the finding, the
way `complexity_languages_not_measured` already does.

**Phase 1 should be Python only.** It covers `http_api` (FastAPI, Flask,
Starlette, Django), `messaging` (Celery, Kafka consumers), `graphql`
(Strawberry/Graphene) and `grpc` (servicer class registration) in one pass, it is
exact, and it produces the §6 worked example on this repository itself.

### 3.2 · Consumption — `interface_surface`, unchanged in shape

`interface_surface.py` stays Discovery, stays zero-fetch, and gains one helper
that is a sibling of `_cli_dunder_main()`:

```
def _registrations(marker_rows, arch_interface_details) -> dict[str, list[dict]]
```

reading, in preference order:

1. `project_code_markers` rows for the slug (the new, general fact);
2. `architecture_interfaces` findings with `detail.kind == "port"` and
   `detail.protocol in {"HTTP/REST", "gRPC", "GraphQL", "Thrift"}` — §1b, worth
   wiring on its own and shippable before the capture exists.

Both are reads of already-stored rows, added to `run()` next to the existing
`query_findings(slug, "distribution")` / `"deployment_evidence"` reads, and both
default to empty so every existing call site and every pre-existing test keeps
working — the same compatibility rule `detect()`'s docstring already states.

**`_ROUTE_LIKE_KINDS` should be renamed, not deleted.** It is currently doing two
jobs: naming the kinds whose `implemented` rung needs registration evidence, and
standing in for "cannot be checked". Split them. Keep the set as
`_REGISTRATION_KINDS` with the first meaning — it is still exactly right, and
`cli` still correctly stays out of it.

**`_COULD_NOT_CHECK_REASON` must survive, with different reasons.** This is the
part most at risk of being "cleaned up" during implementation, and it is the part
that matters. After the capture lands there are **three** outcomes where there
are two today, and collapsing them would reintroduce the exact defect
`find-absence-as-answer` describes:

| outcome | condition | what it says |
|---|---|---|
| `implemented` | markers found for this kind | *N routes across M modules* |
| `implied` + measured zero | the capture **ran**, covered this language, found no registration | the dependency is present and nothing registers with it — a real finding about the repository |
| `implied` + `could_not_check` | `repo_symbol_extraction` has not run for this repo, **or** the repo's languages are outside `_MARKER_CAPABLE_LANGUAGES` | a finding about us |

So `_COULD_NOT_CHECK_REASON`'s values change from *"route decorators are not
recorded"* (a permanent statement about the pipeline) to a reason computed per
repo — `"no code-marker extraction has run for this repository"` or
`"route registrations are not captured for go, javascript"`. The middle row is
new and is the one that only becomes sayable once the capture exists.

`_CONFIDENCE` needs no change: `IMPLEMENTED: 90` already sits where a
code-observed fact belongs, below a committed contract.

### 3.3 · `docs/dr-egeria/resource_questions.csv` — *What are the public interfaces?* (line 53)

**Not edited in this change.** Recommended edits, for the implementation PR:

- **`Answering Analysis` stays `interface_surface`.** Do **not** make it
  `MIXED: interface_surface; api_structure`. `api_structure` does not answer this
  question at any tier — it reads the same symbol table and would inherit the
  same gap. `repo_symbol_extraction` is a *step precondition* of the answer, not
  a second answering analysis, and `MIXED:` would tell a reader to look somewhere
  that has nothing for them. The precedent in the file is that `MIXED:` names
  analyses that each answer part of the question; this is not that shape.
- **The `Notes` column's `Open:` text is replaced**, not deleted, and only when
  the capture ships. Until then it is accurate and should stay. Its replacement
  should say what the answer now depends on: *"`implemented` for http_api/grpc/
  graphql/messaging requires `repo_symbol_extraction` to have run (it writes
  `project_code_markers`); where it has not, or where the repo's languages are
  outside marker coverage, the rung reports could_not_check with the reason
  rather than guessing implied."* The dependency becoming visible in the Notes
  column is the point — it is the thing a reader needs in order to know why one
  repo answers and another does not.
- The `Description` column's Discovery-altitude framing (*"is there a published
  contract" rather than "what symbols exist"*) is **correct and unchanged.** The
  fix does not raise the altitude; it supplies the altitude's missing input.

### 3.4 · `analysis_catalog.yaml`

`interface_surface` keeps `intent: discovery`, `run_time: fast`,
`availability: inline`. Only its `description` changes, at the clause beginning
*"Where code-level evidence would exist but no Discovery-tier step records it…"*
— which becomes a statement about *whether the capture has run for this repo*
rather than about the pipeline never recording it.

### 3.5 · Order of work

1. **Read `architecture_interfaces` ports** (§1b). No schema change, no capture,
   ships alone, and immediately produces the §6 worked example on FastAPI repos
   that have had `repo_arch_detect` run.
2. **`project_code_markers` + Python capture** (§3.1). The general fix.
3. **Java/Spring markers.** Largest remaining coverage gain.
4. **Re-point `egeria_interfaces`** at the same table if import/call-site capture
   is added later — same root cause, and it should not be fixed twice.

---

## Open questions for the project owner

1. **Does `repo_interface_surface` gain a declared precondition on
   `repo_symbol_extraction`?** This is the tier question with real teeth. A
   precondition makes the answer reliably available, and puts a
   `fetch_cost="download"`, `compute_cost="medium"` step in front of a step whose
   entire justification is that it is cheap enough to gate the expensive tiers
   (CLAUDE.md rule 17). The alternative — no precondition, `could_not_check`
   whenever extraction happens not to have run — keeps Discovery cheap and makes
   the answer's availability depend on survey ordering. **Recommended: no hard
   precondition**; bundle the two under the `interface_surface` ANALYSIS_KINDS
   entry the way `api_structure` already bundles `repo_symbol_extraction`, so
   *asking for* interfaces is self-refreshing while the Discovery step itself
   stays free-standing. Owner's call.
2. **Separate `project_code_markers` table, or columns on
   `project_code_symbols`?** Recommended above as a separate table (the unique
   key cannot hold N registrations per symbol). Worth confirming, since it is a
   migration either way.
3. **Phase-1 language scope: Python alone, or Python + Java together?** Python
   alone is exact, free, and self-demonstrating on this repo. Java/Spring is
   where the surveyed corpus's weight actually sits.
