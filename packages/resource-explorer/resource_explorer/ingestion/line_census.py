"""Per-language line census: code, comment, docstring, blank.

Why this exists
---------------
`project_stats.ingestion_lines_of_code` counts every newline in every
text-suffixed file and is named as though it counted code. Measured on
egeria-python 2026-09-01: it reports 1,118,195, and actual Python code lines
are 156,297 — 14%. The rest is JSON (40.7% of all lines), Markdown (28.2%),
docstrings (25.7% of Python lines) and blanks (13.0%).

Dan, on being told a rename was the fix: *"I don't think its just a rename -
the decomposition itself is interesting/important."* This is the
decomposition. See docs/code-volume-and-doc-coverage-design.md D1.

What it refuses to do
---------------------
**It does not guess.** A comment counter that treats every `//` as a comment
miscounts `"https://example.com"`, and a wrong number under a right label is
the defect this whole exercise exists to remove. So each language is handled
by a scanner that understands that language's string literals, or it is not
categorised at all.

Three tiers, and a file lands in exactly one:

* `python`   — tokenised by the standard library. Exact, and the only tier
  that can separate a docstring from a string expression.
* `c_family` / `hash` — a small state machine that tracks string and char
  literals (with escapes) before deciding a `//`, `/* */` or `#` begins a
  comment.
* `uncategorised` — Markdown, JSON, HTML, CSS, SQL, XML, plain text. Lines
  are counted and reported as text, never folded into a code total. "1,065
  Markdown files, 262,375 lines" is a useful fact; adding it to a code figure
  is precisely today's defect.

A language absent from `_LANGUAGE_BY_SUFFIX` is not counted at all rather
than being counted badly.
"""
from __future__ import annotations

import io
import logging
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: suffix -> (language name, scanner tier)
_LANGUAGE_BY_SUFFIX: dict[str, tuple[str, str]] = {
    ".py": ("python", "python"),
    ".js": ("javascript", "c_family"), ".jsx": ("javascript", "c_family"),
    ".ts": ("typescript", "c_family"), ".tsx": ("typescript", "c_family"),
    ".java": ("java", "c_family"),
    ".go": ("go", "c_family"),
    ".rs": ("rust", "c_family"),
    ".c": ("c", "c_family"), ".h": ("c", "c_family"),
    ".cpp": ("cpp", "c_family"),
    ".cs": ("csharp", "c_family"),
    ".swift": ("swift", "c_family"),
    ".kt": ("kotlin", "c_family"),
    ".scala": ("scala", "c_family"),
    ".rb": ("ruby", "hash"),
    ".sh": ("shell", "hash"), ".bash": ("shell", "hash"),
    ".r": ("r", "hash"),
    ".yaml": ("yaml", "hash"), ".yml": ("yaml", "hash"),
    ".toml": ("toml", "hash"),
    # Counted, never categorised, never added to a code total.
    ".md": ("markdown", "text"), ".rst": ("rst", "text"),
    ".txt": ("text", "text"), ".json": ("json", "text"),
    ".html": ("html", "text"), ".css": ("css", "text"),
    ".xml": ("xml", "text"), ".sql": ("sql", "text"),
}


#: Directories whose contents are not this project's own code.
#:
#: Found by running the census against a real checkout: it reported 6,989
#: Python files and 1.76M code lines for egeria-python, against 617 tracked
#: files and 156,902 code lines. The difference was `.venv`. An ingested
#: zipball does not carry a virtualenv, but a repo with a committed `vendor/`
#: or `node_modules/` would inflate exactly the same way — and "how much code
#: is there" answered with somebody else's library is a wrong answer, not a
#: generous one.
_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", "virtualenv", "site-packages",
    "node_modules", "bower_components", "vendor",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", "target", "out", ".next", ".nuxt",
    ".idea", ".vscode", ".gradle", ".eggs",
})


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        parts = path.parts[:-1]
    return any(part in _EXCLUDED_DIRS or part.endswith(".egg-info") for part in parts)

@dataclass
class LanguageCensus:
    files: int = 0
    code: int = 0
    comment: int = 0
    docstring: int = 0
    blank: int = 0
    #: True when this language's lines are counted but not categorised —
    #: markdown, JSON and friends. Their `code` is always 0 and must never be
    #: read as "no code": nothing was categorised at all.
    text_only: bool = False

    @property
    def total(self) -> int:
        return self.code + self.comment + self.docstring + self.blank

    def as_dict(self) -> dict:
        return {
            "files": self.files, "code": self.code, "comment": self.comment,
            "docstring": self.docstring, "blank": self.blank,
            "total": self.total, "text_only": self.text_only,
        }


def _census_python(src: str) -> tuple[int, int, int, int]:
    """(code, comment, docstring, blank) via the standard tokeniser.

    A syntax error raises, and the caller falls back to `hash` scanning
    rather than dropping the file: an uncountable file must not silently
    reduce the total, which would understate size and read as smaller code.
    """
    comment_lines: set[int] = set()
    doc_lines: set[int] = set()
    code_lines: set[int] = set()
    _IGNORED = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER,
                tokenize.ENCODING}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            comment_lines.add(tok.start[0])
        elif tok.type == tokenize.STRING and tok.line.lstrip().startswith(('"""', "'''")):
            doc_lines.update(range(tok.start[0], tok.end[0] + 1))
        elif tok.type not in _IGNORED and tok.string.strip():
            # Real code tokens are tracked explicitly, so a line carrying
            # BOTH code and a trailing comment counts as code. The first
            # draft classified `url = "http://x"  # note` as a comment
            # line, which inflates comments and deflates code -- wrong,
            # and wrong in the direction that flatters.
            code_lines.add(tok.start[0])

    code = comment = docstring = blank = 0
    for i, line in enumerate(src.splitlines(), 1):
        if not line.strip():
            blank += 1
        elif i in code_lines:
            code += 1
        elif i in doc_lines:
            docstring += 1
        elif i in comment_lines:
            comment += 1
        else:
            code += 1
    return code, comment, docstring, blank


def _census_scanned(src: str, *, block: bool, hash_comments: bool) -> tuple[int, int, int, int]:
    """(code, comment, 0, blank) with string literals respected.

    The whole point: `url = "https://x"` is a code line, not a comment. A
    naive `'//' in line` check calls it a comment, and on a codebase full of
    URLs that is a large, quiet error in the flattering direction.
    """
    code = comment = blank = 0
    in_block = False
    for raw in src.splitlines():
        line = raw.strip()
        if not line:
            blank += 1
            continue

        saw_code = False
        saw_comment = False
        i, n = 0, len(raw)
        quote = ""
        while i < n:
            ch = raw[i]
            if in_block:
                if block and raw.startswith("*/", i):
                    in_block = False
                    i += 2
                    continue
                saw_comment = True
                i += 1
                continue
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = ""
                i += 1
                continue
            if ch in "\"'`":
                quote = ch
                saw_code = True
                i += 1
                continue
            if block and raw.startswith("//", i):
                saw_comment = True
                break
            if block and raw.startswith("/*", i):
                in_block = True
                saw_comment = True
                i += 2
                continue
            if hash_comments and ch == "#":
                saw_comment = True
                break
            if not ch.isspace():
                saw_code = True
            i += 1

        if saw_code:
            code += 1
        elif saw_comment:
            comment += 1
        else:
            code += 1
    return code, comment, 0, blank


def census_source(text: str, suffix: str) -> tuple[str, tuple[int, int, int, int]] | None:
    """(language, (code, comment, docstring, blank)) for one file's text, or
    None when the suffix is not one we count."""
    entry = _LANGUAGE_BY_SUFFIX.get(suffix.lower())
    if entry is None:
        return None
    language, tier = entry

    if tier == "text":
        return language, (0, 0, 0, 0)
    if tier == "python":
        try:
            return language, _census_python(text)
        except (SyntaxError, tokenize.TokenError, IndentationError, ValueError):
            # Unparseable Python still has lines. Fall back to hash scanning
            # rather than dropping it.
            return language, _census_scanned(text, block=False, hash_comments=True)
    if tier == "c_family":
        return language, _census_scanned(text, block=True, hash_comments=False)
    return language, _census_scanned(text, block=False, hash_comments=True)


def census_tree(root: Path, rel_paths: list[str] | None = None) -> dict[str, LanguageCensus]:
    """Walk `root` (or just `rel_paths` under it) and total by language.

    Unreadable files are skipped with a debug log and NOT counted — the
    alternative, counting them as zero lines, would quietly shrink the
    measured size.
    """
    out: dict[str, LanguageCensus] = {}
    paths = ([root / p for p in rel_paths] if rel_paths is not None
             else [p for p in root.rglob("*") if p.is_file()])
    for path in paths:
        entry = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if entry is None or not path.is_file():
            continue
        if _is_excluded(path, root):
            continue
        language, tier = entry
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("line_census: unreadable %s: %s", path, exc)
            continue

        c = out.setdefault(language, LanguageCensus(text_only=(tier == "text")))
        c.files += 1
        if tier == "text":
            # Counted as blank-or-content lines without categorisation; the
            # total is meaningful, `code` deliberately is not.
            c.blank += text.count("\n")
            continue
        result = census_source(text, path.suffix)
        if result is None:
            continue
        _, (code, comment, docstring, blank) = result
        c.code += code
        c.comment += comment
        c.docstring += docstring
        c.blank += blank
    return out


def code_line_total(census: dict[str, LanguageCensus]) -> int:
    """Code lines across categorised languages only.

    Text-only languages are excluded by construction — that exclusion IS the
    fix. Folding Markdown and JSON into a code figure is what produced
    1,118,195.
    """
    return sum(c.code for c in census.values() if not c.text_only)
