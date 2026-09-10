# The `/next` UI experiment

A parallel web UI at `/next`, served alongside `/` by the same FastAPI app,
implementing the design handed off as *"skin 1c + answer-in-the-row"*: a
"dark chrome, paper content" skin behind a named token layer, and one
redesigned screen — the Questions checklist, changed from reporting **how** a
question would be answered to reporting **what the answer is**.

No endpoint, schema or migration changed. The whole UI is a consumer of
`/api/*`, so this is additive and reversible: if it is a dead end, delete
`static/next/`, `frontend-build/tailwind-next.config.js`, and the `/next`
route.

## What is here

| Path | What it is |
|---|---|
| `resource_explorer/web/static/next/index.html` | the shell — chrome, login overlay, responsive grid |
| `resource_explorer/web/static/next/app.js` | the app; rendering, state, the envelope reader |
| `resource_explorer/web/static/re-api.js` | the API client, as a shared ES module |
| `resource_explorer/web/static/next/fonts/` | self-hosted Cormorant Garamond + Lora |
| `frontend-build/tailwind-next.config.js` | the token layer; a SECOND Tailwind entry |
| `frontend-build/build-next-fonts.py` | regenerates the vendored fonts |
| `web/app.py` `GET /next` · `auth.py` `RE_PUBLIC_PATHS` | the two lines of wiring |

Build the stylesheet with `npm run build:css:next` (or `npm run build`, which
now runs both entries). The two Tailwind builds are independent: `build:css`
still content-scans `index.html` only and emits `static/tailwind.css`, so a
mistake in either stylesheet cannot reach the other UI.

## Scope

The frame, plus **one** pane: Questions, for a repo.

That pane is **parameterised by stage** rather than duplicated per stage —
the questions endpoint already takes `phase`, and this matters for more than
tidiness. Scouting's five questions are `analysis` and `direct` only; `gap`,
`human`, `mixed`, `partial` and `chart` all live in Analysis and Enrichment.
A Scouting-only build would have shipped a screen whose entire argument —
that six row states are scannable as glyph plus sentence — could not be
looked at.

Every other sub-tab (Search, Survey, Dashboard, Disposition) renders "not
built in /next" at full legibility. So do Investigation and Understanding.
Databases and filesystems are repo-only here.

## What the handoff got wrong, verified against the running app

The handoff document says its authors had read-only access and could not run
anything, and asks that claims about existing behaviour be checked. Two were
wrong, one materially:

**"The answer and caveat text do not exist as fields yet."** They do.
`GET /api/analyses/facts/{slug}/answer?question=…` returns a `facts.py`
`Envelope` carrying exactly what a row needs: a per-analysis `state` from
`surveyors/result_status.py`'s vocabulary, a written `headline`, a `note`
that is the caveat, `last_run_at`, `can_run`, and `blocked_reason` when the
question cannot be answered at all. The handoff's preferred option — "the
questions endpoint gains an answer projection" — is unnecessary; the
projection is a second endpoint that already exists. `/next` calls it once
per row, which is also what gives rows their independent arrival.

**"`GET /api/activity/{id}` — poll a run to completion".** Correct, but the
list endpoints it sits beside (`/api/activity/`, `/api/activity/rfas`) page,
with defaults of 200 and 500. A returned length equal to the limit is a full
page, not a total. `/next` renders those as `200+`.

## Three bugs this screen found in its own first hour

Recorded because each is the shape the project keeps rediscovering, and each
was invisible until the screen was pointed at real data.

1. **A tick beside "never run".** Most facts come back with `state:
   "measured"` and an EMPTY `last_run_at`. Rendering an absent timestamp as
   "never run" put a ✓ and a claim that nothing had ever run in the same row.
   Missing timestamp is a gap in the record, not evidence about the
   repository: the three cases are now "run 19d ago", "run time not
   recorded", and "never run".

2. **A tick with nothing under it.** Most analyses have no `headline_reader`
   wired up, so the answer line was empty while the row claimed to be
   answered. There is now a fallback ladder — headline, then the analysis's
   own `detail`/`summary` prose with its own `verdict` word, then the scalar
   measures with a caveat naming the analyses that have no written summary.
   Every rung relays something the analysis wrote; none composes a verdict.

3. **A perspective that matched nothing said nothing.** The "matches nothing
   here" chip was computed from the FILTERED question set, which inverts the
   answer in exactly the case the chip exists for: hold `Privacy`, every
   question is hidden, so the "matched" set is empty too and the chip renders
   as ordinary. It is computed from the stage's unfiltered set now.

There was also a rendering bug worth its own line: `esc()` emitted `&#39;`
for an apostrophe and `tnum()` then wrapped the `39` in a span, so the page
displayed `Egeria&#39;s catalog`. `esc()` uses named entities only now.

## Two decisions still open — they need the design owner

The handoff names both as cheap now and expensive to retrofit. Neither was
answered before building, so `/next` implements the design as designed and
flags them here.

**1. Does state stay hue-coded?** `/next` follows skin 1c: one gold accent,
state carried by glyph and weight. If green and amber must survive, they need
adding as named roles (`state-ok`, `state-warn` — never `green-500`) holding
at least 3:1 against *both* grounds, which the current amber does not manage
on paper.

**2. Which density?** `/next` uses the design system's airy 1.15× scale
(4.6 / 9.2 / 13.8 / 18.4 / 27.6 / 36.8px), which is looser than the current
UI. Spacing is the one thing a find-and-replace cannot reason about, so this
is worth settling before any of this reaches `index.html`.

## Exit criteria — not yet agreed

The handoff is right that "looks better" is not a bar, and that failing to
name one leaves a third thing to maintain. Its suggestion, unchanged and
still needing a yes or no:

> A tester answers the scouting questions for an unfamiliar repo faster in
> `/next`, and can correctly state which claims have not been run.

Meet it, then either codemod `index.html` or grow `/next` screen by screen
and retire the old one — but name which, before starting.

**What this cannot settle**, also from the handoff and worth repeating: it
says nothing about the work list (which needs a batch-enqueue endpoint that
does not exist), nothing about scale while it loads one resource at a time,
and it will flatter itself on performance because a new shell carries none of
the accumulated listeners the old one does.

## Round 2 — the regression review

The design owner reviewed the first build and raised nine losses, with a
correction to their own handoff: *"a parallel UI may defer any affordance,
but it may not silently omit one."* The first pass read "stub the chrome" as
licence to drop things that looked like frame and were function — a sub-tab
rail, a resize handle, a chat drawer, a state legend.

### The two readability fixes

**#1 — text too light.** The diagnosis offered was that the answer line had
picked up a muted token. It had not: the answer line measured `#201f1d` at
14.5px with Lora loading correctly. The real cause was next door — the
*question title* was muted for the unrun, no-surveyor and unclassified
states, and so was the whole body line for those rows. On the Analysis stage
that is most of the page. So de-emphasis had crept back in as fading text,
which is the one thing this palette forbids.

The correction was right even though the cause was not: no line that carries
content uses a muted token now (muted is labels, provenance and metadata
only), the glyph carries the state, and body and answer text went to 15px.

**#6 — no key for the symbols.** Restored as a counted legend under the
stage line — `✓ answered 3 · ✓ automatic 1 · ○ not run 1` — listing only the
states actually present, and re-rendering as rows arrive.

### The honesty pass

**#3** — the four unbuilt sub-tabs now carry the same dashed marker the
unbuilt intent uses, and clicking one opens a panel that says so and links
out. The same treatment reached Activity, RFAs and Admin in the chrome:
their counts stay live, the surfaces link to the current UI.

One thing that panel cannot do is preserve the resource. **The current UI has
no deep link** — its navigation state lives in JavaScript variables, not the
URL — so the panel says plainly that you will have to reselect. `/next` now
has one (`?resource=&stage=&tab=&perspectives=`), which the inventory lists
as a Keep and which neither UI had.

### The keeps

**#7, selection and grouping** — restored whole: the resource-type facet, the
text filter, the five lifecycle scope chips, disposition facets, Select mode
with bulk actions, the group tree, Show hidden, and per-resource status marks
(typographic, not emoji: `▣ ▤ ▢` for published/surveyed/new, `● ◎ ✚` for
using/investigating/recommended).

Two things worth knowing about that:

- Disposition zeros are **collapsed behind a "N more…" control, not
  removed**. The handoff's "show only non-zero counts" was advice about
  noise; as a spec it removed the controls, and a facet you cannot select is
  a filter you cannot undo.
- `GET /api/projects/` filters harder than its parameter names suggest:
  `include_ignored=false` drops **`abandoned` as well as `ignored`**, and
  `include_working_set_hidden=false` drops hidden repos. `/next` asks for the
  full list and filters client-side, or those facets could never be
  populated.

**#8, write paths** — remove, hide/unhide and disposition are on the resource
header, plus their bulk equivalents in Select mode. Notes on each:

- `DELETE /api/projects/{slug}` takes **no confirmation flag of any kind**
  and drops the repo's pgvector collections along with the registry row. The
  only confirmation that can exist is the client's, so it names what is
  going, says it cannot be undone, and says how it differs from marking a
  repo *ignored* — which leaves it registered.
- Disposition is keyed on **`github_url`, not the slug**. A repo with no
  GitHub URL cannot be dispositioned, and the header says that rather than
  appearing to work.
- There are **seven** legal dispositions, not four: `undecided`, `tracking`,
  `investigating`, `recommended`, `using`, `abandoned`, `ignored`.
- Every bulk write reports per-resource. A partial failure never renders as
  success.

**#9, external links** — GitHub and the project site, marked external and
visually distinct from internal navigation. There is **no separate docs
link**: `homepage` is already the derived best link (GitHub's declared
homepage, then the packaging manifest, then the README) and does duty as
both. It lives on the scouting overview, not the summary row, so the header
fetches it per selection and renders without it if that call fails.

**#2, resizable panes** — both seams drag, with keyboard support, and both
widths persist. Bounds are 150–520px for the sidebar and 220–620px for the
rail.

**#4 and #5, the chat drawer** — it toggles, remembers its state, overlays
rather than squeezing below 1100px, and keeps a transcript. Each turn is
labelled with the resource it was asked about and marked when that is not the
current selection. Each answer carries its source line, the three-state
feedback control, and an *Open as candidates* action when the answer looks
like a list.

The feedback vote is **three states, not a thumb pair**: `+1` / `0` /
`-1`, where `0` is "partly right". That middle value is the one that
separates a routing problem from a content problem, and folding it into
either neighbour would lose the signal the vote exists to collect. The
`query_hash` always comes off a server response — never computed here — so a
vote lands under the same key however the answer was produced.

**The current investigation** is in the chrome and switchable from the
sidebar. There is no server-side notion of a current investigation; the
existing UI keeps it in `localStorage` under `re_current_investigation`, and
`/next` reads and writes **the same key**, so switching shells does not
silently change what you are working on.

### A third instance of the same bug

The evidence panel was still saying "never run" for a fact whose state is
`measured` and whose `last_run_at` is empty — the same conflation fixed in
the row last round, in a second place. It now says "run time not recorded"
there too. Worth noting because it is the pattern: the fix went where the bug
was seen, not everywhere the mistake was made.

### Not verified

**The chat success path.** `POST /api/query/` requires a real session, and
the verification instance runs with `TRELLIS_ANONYMOUS_READ=true`, which
permits reads only. The turn's *error* rendering is verified against a live
401; the answer, source line, feedback control and candidates action are
written but have not been seen with a real response. Signing in is what would
settle it.

## Round 3 — the fix round

Working order: `FIX-ROUND.md` in the design bundle, with two reversals of the
original spec and a section on diagrams that the spec never covered.

### Hue is back

The first spec removed hue-coded state because the bound design system is
mono by construction. That was the system's constraint applied where it does
not belong: a list of rows scanned for exceptions is where hue earns its
keep. State is now **glyph *and* colour** — the glyph survives printing,
greyscale and colour blindness and is what the legend keys; the hue is what
makes the column scannable.

The instruction was for named roles "each holding at least 4.5:1 against both
grounds". **No single colour can do that**, and this is arithmetic rather
than opinion: passing on paper needs luminance ≤ 0.159, passing on chrome
needs ≥ 0.222, and that window is empty. So each role has two variants, the
same split that already forced `ink-muted` and `chrome-muted`:

| Role | On paper | On chrome | Used for |
|---|---|---|---|
| `state-ok` | `#1d6b3f` 5.82:1 | `#74c68d` 8.44:1 | answered, automatic |
| `state-warn` | `#9c4212` 5.87:1 | `#f2a26a` 8.40:1 | not run |
| `state-gap` | `#5b4a9c` 6.47:1 | `#a99ae0` 6.94:1 | no surveyor |
| `accent` (gold) | `#7d5411` 5.97:1 | `#e1ad66` 8.58:1 | needs your attention |

**Known risk, stated rather than hidden:** `state-warn` and gold are both
warm and within 1.02:1 of each other in luminance, so on the same ground they
separate by hue alone. Tolerable only because colour is never the sole
channel — the two states carry different glyphs (`○` vs `⚠`) and different
words in the legend. If they turn out to be confusable in use, warn is the
one to move.

Also raised: the chip border was `#d7d3d3` at **1.33:1**, well under the 3:1
a UI boundary needs. Now `#8e8a8a` at 3.05:1.

### Icons in, emoji out — metaphor kept

Two substitutions in the previous round went too far and are reverted to
pictograms, via a vendored Lucide sprite
(`frontend-build/build-next-icons.py` → `static/next/icons.svg`, injected so
`currentColor` inherits):

- **Feedback** — `yes / partly / no` became words, turning a one-glance
  control into reading. Back to `thumbs-up` / `minus` / `thumbs-down`.
- **Sidebar marks** — `▣ ▤ ▢` was abstract geometry needing a key where a
  metaphor had landed. Back to `cloud` / `bar-chart-2` / `sparkles`, plus
  `eye` / `microscope` / `badge-check` / `circle-check` for dispositions.

The rule now followed: nearest Lucide equivalent of the **same** metaphor, at
14–16px, inheriting `currentColor`. Only the six question states use an
abstract glyph, because no metaphor exists for them and a legend keys them.

### The five items from the side-by-side walk

- **Disposition history** restored, under the picker. The field is
  `decided_at` (verified against the endpoint, not guessed), and `decided_by`
  renders only when set rather than showing an empty attribution.
- **Facet count scoping** — `/next` counts every registered repo and now
  **says so** in the label; the current UI counts the investigation's working
  set. One was picked and named, as instructed.
- **GitHub link back on every sidebar row**, as well as on the header.
- **The deferred "Search" stub renamed** to what it is: *Repo discovery —
  find and import candidate repos*. Each deferred sub-tab now states its own
  job rather than inheriting a label that mis-describes it.
- **All perspectives per row**, wrapping. Seeing that a question carries four
  is how you learn the axis barely filters.

### The current UI gained one deep link

"Links out **preserving the current resource**" was not satisfiable: the
current UI had no URL state at all. `index.html` now reads `?resource=<slug>`
on boot and selects it — deliberately narrow and additive, it selects a
resource and nothing else, runs after the normal boot rather than replacing
any of it, does not write the URL back, and quietly ignores a slug that is
not registered. Verified both ways: `/?resource=egeria_workspaces_git` lands
on that repo, and a bare `/` still boots with nothing selected.

This is the first edit to `index.html` in this experiment. It adds no Tailwind
classes, so `tailwind.css` is unchanged.

### Diagrams and charts

Not in the original spec at all. They live in the **content pane, on paper** —
which is a real dividend of the chrome/paper split, since Mermaid, Plotly and
Kroki all default to a light ground and need no dark override there.

- **Token-bound, with the tokens read back off the live stylesheet** via a
  hidden probe element carrying the classes. Restating the palette in JS
  would put it in two places, which is what the token layer exists to
  prevent.
- **`font-diagram`** (the mono stack) for every node label, axis tick and
  legend — the one place the type system is deliberately overridden.
- **A diagram cannot live in the rail** at 290px, so a chart or diagram
  answer shows a marker there and an **"open in pane"** action that promotes
  it to full width, with `svg-pan-zoom` attached for SVG. Both libraries were
  already vendored.
- **Form follows answer shape**, not the model's preference: scalar inline,
  ranked list as a list, anything over time as a chart in the pane,
  relationships as Mermaid in the pane, cross-resource as the work-list grid
  (which does not exist yet).

Mermaid renders server-side through `POST /api/diagrams/mermaid`, which
returns **raw SVG as `image/svg+xml`, not JSON** — a first attempt parsed it
as JSON and would have failed on every diagram.

**Unverified end to end.** Reaching a chart or a diagram needs a real chat
answer, and `POST /api/query/` needs a session the anonymous-read verification
instance does not have. The rendering path, the theme binding and the
promotion mechanism are written and syntax-checked; none has been seen with a
real figure.

## Known gaps

- **`re-api.js` is shared in location only.** `index.html` does not import it
  yet. Rewiring it is a separate change with its own verification, because
  the inlined copies there carry behaviour (toasts, view routing) this module
  deliberately does not. Until that lands, the drift the module exists to
  prevent is only half-prevented.
- **No deep link.** Neither UI has one, so "open the current UI" in the
  chrome is the app root, and the selection does not carry across. That
  weakens the side-by-side comparison the handoff asks for.
- **Enrichment rows cannot be answered inline.** The `⚠` row says so rather
  than offering a form.
- **Deferred, per the affordance inventory:** survey cards (run, schedule,
  notify, results, steps), sub-resources and scoped analysis, Curate
  verdicts, the Context form, Automate, the Activity log, the RFA drawer,
  Admin, and the stat tiles. Each is marked and linked out; none is silently
  absent.
- **The work-list grid does not exist**, so the "one question across several
  resources" row of the form table has nowhere to go. It needs a batch-enqueue
  endpoint that does not exist either.
- **Lucide is not wired in.** The screen needs almost no icons: its state
  vocabulary is typographic (`✓ ○ ⚠ ·`), which is not emoji and not an icon
  set. Add the sprite when a surface actually needs one.
