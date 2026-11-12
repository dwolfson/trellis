# trellis-ui

The browser pieces Resource Explorer and Egeria Advisor share, served by each app at `/static/trellis-ui/`:
the three looks (`themes.css`, `look.js`), resizable table columns (`colresize.js`),
markdown rendering (`markdown.js`), the run-envelope renderer with its formatting helpers
(`envelope.js`, `format.js`), and pyegeria's structured TABLE renderer (`egeria-table.js`).

`egeria-table.js` is **vendored unchanged** from the Egeria Portal (odpi/egeria-workspaces), so the Portal and
Egeria Advisor draw a report spec's TABLE the same way. `egeria-table.js.source.json` names the source commit
and the file's sha256, and EA's `tests/unit/test_dashboard_structured_table.py` (`test_vendored_egeria_table_is_the_portals_file_unchanged`) fails if the copy drifts. Never edit
it here: an app's own needs go through its options (`linkBuilder`). To update it, copy the new file as is and
change the record.

The files ship as package data; an app serves them with `trellis_ui.mount(app)`, called **before** its own
`/static` mount. See `trellis_ui/__init__.py`.

`themes.css` is the one place the looks' colours live. Each app maps its own Tailwind names onto its
variables: RE in `frontend-build/tailwind-next.config.js`, EA in the `tailwind.config` block in each page's
`<head>`. Contrast is checked by RE's `tests/test_themes_contrast.py` and, for EA's pages, by
`packages/egeria-advisor/tests/unit/test_looks_contrast.py`.
