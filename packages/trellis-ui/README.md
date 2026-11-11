# trellis-ui

The browser pieces Resource Explorer and Egeria Advisor share, served by each app at `/static/trellis-ui/`:
the three looks (`themes.css`, `look.js`), resizable table columns (`colresize.js`),
markdown rendering (`markdown.js`), and the run-envelope renderer with its formatting helpers
(`envelope.js`, `format.js`).

The files ship as package data; an app serves them with `trellis_ui.mount(app)`, called **before** its own
`/static` mount. See `trellis_ui/__init__.py`.

`themes.css` is the one place the looks' colours live. Each app maps its own Tailwind names onto its
variables: RE in `frontend-build/tailwind-next.config.js`, EA in the `tailwind.config` block in each page's
`<head>`. Contrast is checked by RE's `tests/test_themes_contrast.py` and, for EA's pages, by
`packages/egeria-advisor/tests/unit/test_looks_contrast.py`.
