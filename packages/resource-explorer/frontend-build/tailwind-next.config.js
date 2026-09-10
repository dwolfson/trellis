/** Tailwind build for the experimental `/next` UI — skin 1c, "dark chrome,
 * paper content".
 *
 * SEPARATE from tailwind.config.js on purpose. That build content-scans
 * index.html and emits static/tailwind.css; this one scans only static/next/
 * and emits static/next/tailwind-next.css. Two entries, two outputs, so the
 * token layer below gets proven on a real screen without one edit to the
 * ~17,900-line index.html — and so a mistake in either stylesheet cannot
 * reach the other UI.
 *
 * The token values are the contrast-audited ones from the design handoff.
 * They live HERE and nowhere else: the whole argument for a named token layer
 * is that a restyle is one file, which a second copy in a CSS custom-property
 * block would immediately undo (see docs/Architecture.md's note on what two
 * copies of one fact bought this project).
 *
 * THE KEY STRUCTURAL FACT: there are two grounds. Chrome is dark, content is
 * paper. Muted text therefore needs TWO tokens — `chrome-muted` on dark,
 * `ink-muted` on paper. A single shared muted role cannot pass contrast on
 * both, and three attempts to make one work by adjusting greys are what
 * produced this split.
 */
module.exports = {
  content: ['../resource_explorer/web/static/next/**/*.{html,js}'],
  theme: {
    extend: {
      colors: {
        // ── Chrome (dark): nav, sidebar, right rail ──────────────────
        chrome: '#1b1a19',              // ground; one step below neutral-900
        'chrome-alt': '#201f1d',        // right rail / secondary chrome ground
        'chrome-surface': '#2d2b2b',    // selected row, raised block
        'chrome-line': '#444141',       // borders and dividers on chrome
        'chrome-line-soft': '#2d2b2b',  // inner hairlines within a panel
        'chrome-ink': '#f3f2f2',        // primary text on chrome
        'chrome-muted': '#9b9797',      // secondary text on chrome — 6.7:1.
                                        // Do not go darker. There is no dim
                                        // role below this one.
        accent: '#b68235',              // strokes, borders, underlines
        'accent-on-dark': '#e1ad66',    // accent TEXT on chrome
        'accent-deep': '#5a3b0a',       // accent border on chrome (accent-800)

        // ── Paper (light): the content pane ──────────────────────────
        paper: '#f3f2f2',
        'paper-surface': '#eae9e9',
        rule: 'rgba(32, 31, 29, 0.16)', // hairline divider
        ink: '#201f1d',
        'ink-muted': '#605d5d',         // secondary text on paper — 6.2:1.
                                        // neutral-400/500/600 all fail here.
        'accent-ink': '#7d5411',        // accent TEXT on paper; #b68235 is
                                        // not legible at body size
        'accent-tint': '#fff3e4',       // selected-row tint
        'rule-strong': '#d7d3d3',       // visible hairline on paper (chips)
      },

      // A 1.15x density scale. Airy by intent — the existing UI is tighter,
      // and mixing the two is the one thing a find-and-replace cannot reason
      // about, so /next commits to this scale throughout.
      spacing: {
        s1: '4.6px',
        s2: '9.2px',
        s3: '13.8px',
        s4: '18.4px',
        s6: '27.6px',
        s8: '36.8px',
      },

      borderRadius: {
        sm: '2px',   // chrome and dense controls
        md: '4px',   // default
        lg: '7px',
        pill: '11px',
      },

      // Elevation is a whisper. Nothing here is a drop shadow.
      boxShadow: {
        sm: '0 1px 2px rgba(45, 43, 43, 0.14)',
        md: '0 3px 10px rgba(45, 43, 43, 0.16)',
        lg: '0 12px 32px rgba(45, 43, 43, 0.22)',
      },

      fontFamily: {
        // Headings, nav, labels, buttons. Interface headings cap at 600;
        // display sizes take the normal cut.
        heading: ['"Cormorant Garamond"', 'Georgia', 'serif'],
        // Body, answers, evidence.
        body: ['Lora', 'Georgia', 'serif'],
        // Qualified names, ids, paths.
        mono: ['ui-monospace', '"SF Mono"', 'Menlo', 'monospace'],
      },

      // The sizes as used on the Questions screen, named by their role so a
      // reader can tell a question title from an answer line without
      // counting pixels.
      fontSize: {
        brand: ['19px', '1.2'],
        intent: ['14px', '1.2'],
        chip: ['11.5px', '1.3'],
        resource: ['12.5px', '1.35'],
        subtab: ['13px', '1.2'],
        name: ['26px', '1.15'],
        question: ['17px', '1.25'],
        // 15px, not the handoff's original 14.5. Lora has a generous
        // x-height but is optically lighter than a grotesque at the same
        // size, and 14.5 was matching the current app's density rather than
        // choosing well — it read as too light on a real screen.
        answer: ['15px', '1.55'],
        caveat: ['13px', '1.5'],
        provenance: ['11.5px', '1.45'],
        caps: ['11px', '1.3'],
      },

      letterSpacing: { caps: '.09em', kicker: '.08em' },
    },
  },
  plugins: [],
};
