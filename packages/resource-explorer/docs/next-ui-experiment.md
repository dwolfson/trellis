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
- **Lucide is not wired in.** The screen needs almost no icons: its state
  vocabulary is typographic (`✓ ○ ⚠ ·`), which is not emoji and not an icon
  set. Add the sprite when a surface actually needs one.
