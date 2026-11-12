"""The browser pieces Resource Explorer and Egeria Advisor share, served at `/static/trellis-ui/`.

The files live in `trellis_ui/static/` and ship as package data, so an app finds them with
`importlib.resources` wherever the package is installed (a checkout, a wheel, an image), never by a
path relative to another package.

    from trellis_ui import mount
    mount(app)          # BEFORE the app's own "/static" mount: Starlette matches mounts in order,
    app.mount("/static", StaticFiles(directory=...))   # and "/static" would otherwise take these paths

What is here (each file says more in its own header):
  themes.css    the three looks (Dark, Light, Paper) as CSS variables, per `data-look` on <html>
  look.js       the look picker; fires `trellis-look-change` (and `re-look-change`, kept as an alias).
                Each page also carries a few inline lines in <head> that set `data-look` from
                localStorage["trellis.look"] before first paint.
  colresize.js  resizable table columns
  markdown.js   markdown to sanitised HTML (needs /static/vendor/marked.min.js, which both apps vendor)
  envelope.js   the run-envelope renderer
  format.js     the time and number formatting envelope.js and RE's pages share
  egeria-table.js  pyegeria's structured TABLE (kind "table") as a table: VENDORED unchanged from the
                Egeria Portal (egeria-table.js.source.json names the commit and sha256); never edited here
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

__all__ = ["STATIC_URL", "mount", "static_dir"]

STATIC_URL = "/static/trellis-ui"


def static_dir() -> Path:
    """The directory holding the shared static files, wherever the package is installed."""
    return Path(str(resources.files("trellis_ui") / "static"))


def mount(app: Any, path: str = STATIC_URL) -> None:
    """Serve the shared files at `path` on a Starlette/FastAPI app. Mount it before the app's own
    "/static", which would otherwise answer `/static/trellis-ui/...` itself (with a 404)."""
    from starlette.staticfiles import StaticFiles

    app.mount(path, StaticFiles(directory=static_dir()), name="trellis-ui")
