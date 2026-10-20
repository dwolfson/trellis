"""The three looks keep their contrast (RULING-THEMES-PORTAL-DARK-LIGHT.md section 3).

Reads `static/next/themes.css`, computes the WCAG ratio for every pair the ruling's table lists, for each look, and
fails a text pair under 4.5 or an outline pair under 3. So a later edit to a palette value cannot quietly fail a pair
that the owner chose a look for.

Run it against a deliberately dimmed token to see it fail: the check is only worth anything if it can.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

THEMES = (Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next" / "themes.css")
LOOKS = ("dark", "light", "paper")

#: (foreground, background) tokens, text. Needs 4.5:1.
TEXT_PAIRS = [
    ("ink", "paper"),
    ("ink", "paper-surface"),
    ("ink-muted", "paper"),
    ("ink-muted", "paper-surface"),
    ("ink-muted", "accent-tint"),        # the selected row
    ("accent-ink", "paper"),
    ("state-ok", "paper"),
    ("state-warn", "paper"),
    ("state-gap", "paper"),
    ("chrome-ink", "chrome"),
    ("chrome-muted", "chrome"),
    ("chrome-muted", "chrome-surface"),
]
#: Strokes and outlines. Need 3:1. The accent stroke has no Paper figure in the ruling ("n/a"): Paper draws its
#: accent as a gold underline that the ruling does not measure.
OUTLINE_PAIRS = [
    ("accent", "paper", {"dark", "light"}),
    ("rule-strong", "paper", {"dark", "light", "paper"}),
]


def _blocks() -> dict[str, dict[str, tuple[int, int, int]]]:
    css = re.sub(r"/\*.*?\*/", "", THEMES.read_text(), flags=re.S)
    out: dict[str, dict[str, tuple[int, int, int]]] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        looks = re.findall(r'data-look="(\w+)"', selector)
        for look in looks:
            tokens = out.setdefault(look, {})
            for name, value in re.findall(r"--c-([a-z\-]+):\s*([^;]+);", body):
                parts = value.split()
                if len(parts) == 3 and all(p.isdigit() for p in parts):    # `rule` is a full colour value, not channels
                    tokens[name] = tuple(int(p) for p in parts)
    return out


def _luminance(rgb: tuple[int, int, int]) -> float:
    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture(scope="module")
def blocks():
    return _blocks()


def test_all_three_looks_define_every_token_the_pairs_use(blocks):
    assert set(blocks) == set(LOOKS)
    needed = {t for pair in TEXT_PAIRS for t in pair} | {t for fg, bg, _ in OUTLINE_PAIRS for t in (fg, bg)}
    for look in LOOKS:
        assert needed <= set(blocks[look]), (look, sorted(needed - set(blocks[look])))


def test_dark_is_the_fallback_when_no_look_is_set():
    """The Dark block's selector must include a bare `:root`, or a page with no data-look has no colours."""
    css = re.sub(r"/\*.*?\*/", "", THEMES.read_text(), flags=re.S)
    dark_selector = next(s for s, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if 'data-look="dark"' in s)
    assert re.search(r"(^|,)\s*:root\s*(,|$)", dark_selector.strip()), dark_selector


@pytest.mark.parametrize("look", LOOKS)
@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_pair_is_at_least_4_5(blocks, look, fg, bg):
    r = ratio(blocks[look][fg], blocks[look][bg])
    assert r >= 4.5, f"{look}: {fg} on {bg} is {r:.2f}:1, text needs 4.5:1"


@pytest.mark.parametrize("look", LOOKS)
@pytest.mark.parametrize("fg,bg,applies", OUTLINE_PAIRS)
def test_outline_pair_is_at_least_3(blocks, look, fg, bg, applies):
    if look not in applies:
        pytest.skip(f"{fg} on {bg} is not measured for {look}")
    r = ratio(blocks[look][fg], blocks[look][bg])
    assert r >= 3.0, f"{look}: {fg} on {bg} is {r:.2f}:1, an outline needs 3:1"


def test_the_ratio_function_is_the_wcag_one():
    """Black on white is 21:1 and a colour on itself is 1:1: pins the arithmetic the rest relies on."""
    assert ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert ratio((120, 130, 140), (120, 130, 140)) == pytest.approx(1.0)
