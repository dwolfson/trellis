"""Screen-defect round of 2026-10-29: header sign-in word, unknown ?stage=, page title, anonymous-read dismiss.

Source-reading tests, the pattern for /next JS without a browser (see test_next_investigation_pane.py)."""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static"
NEXT = STATIC / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


class TestSignedInWord:
    def test_header_and_popover_read_the_one_helper(self):
        app = _app()
        assert "signedInUser() || 'not signed in'" in app
        assert "openConnectionPopover(document, btn, { me: { user_id: signedInUser() } })" in app

    def test_helper_falls_back_to_the_session_token(self):
        app = _app()
        body = app[app.index("function signedInUser()"):]
        body = body[:body.index("\n}\n")]
        assert "Auth.isAuthenticated()" in body and "Auth.getUser()" in body


class TestUnknownStage:
    def test_unknown_stage_is_guarded_before_label_is_read(self):
        app = _app()
        load_pane = app[app.index("async function loadPane()"):]
        find = load_pane.index("STAGES.find((s) => s.id === state.stage)")
        guard = load_pane.index("if (!stageDef) {", find)
        label = load_pane.index("stageDef.label", find)
        assert guard < label

    def test_guard_names_the_stage_and_lists_the_real_ones(self):
        app = _app()
        assert "`no stage named ${state.stage}`" in app
        assert "STAGES.map((s) => s.id).join(', ')" in app


class TestNoNextInScreenWords:
    def test_title_has_no_route_name(self):
        html = (NEXT / "index.html").read_text(encoding="utf-8")
        assert "<title>Resource Explorer</title>" in html

    def test_no_user_visible_next_in_strings(self):
        for f in [NEXT / "app.js", *sorted((NEXT / "stages").glob("*.js"))]:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                s = line.strip()
                if s.startswith(("//", "*", "/*")):
                    continue
                assert "in /next" not in s and "/next stopped" not in s and "; /next counts" not in s, f"{f.name}:{n}"


class TestAnonymousDismiss:
    def test_dismiss_button_is_hidden_unless_anonymous_read(self):
        js = (STATIC / "auth.js").read_text(encoding="utf-8")
        assert "anonymousRead = data.anonymous_read === true;" in js
        assert "dismiss.style.display = anonymousRead ? '' : 'none';" in js
