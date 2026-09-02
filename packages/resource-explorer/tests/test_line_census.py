"""Code volume, decomposed — and the ways a line counter lies.

`project_stats.ingestion_lines_of_code` counts every newline in every
text-suffixed file and is named as though it counted code. Measured on
egeria-python 2026-09-01: it reports 1,118,195; real Python code lines are
156,902 — 14%. JSON is 40.7% of all lines, Markdown 28.2%.

Dan, on being told a rename was the fix: *"I don't think its just a rename -
the decomposition itself is interesting/important."* See
docs/code-volume-and-doc-coverage-design.md D1.

Three defects are pinned here, and every one of them was found by running the
thing rather than by reading it:

1. **A URL is not a comment.** `const u = "https://x"` must count as code. A
   naive `'//' in line` check calls it a comment, quietly, on every file that
   mentions a URL.
2. **A line with code and a trailing comment is code.** The first draft of
   `_census_python` classified `url = "http://x"  # note` as a comment,
   because it tested `comment_lines` before code. That moved 598 lines out of
   code on egeria-python alone — in the direction that flatters.
3. **A virtualenv is not your code.** The first run of `census_tree` against
   a real checkout reported 6,989 Python files and 1.76M code lines against
   617 tracked files. The difference was `.venv`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from resource_explorer.ingestion.line_census import (
    census_source, census_tree, code_line_total)


class TestStringLiteralsAreNotComments:
    @pytest.mark.parametrize("suffix,src", [
        (".js", 'const u = "https://example.com/a";'),
        (".go", '\treturn fmt.Sprintf("//%s", p)'),
        (".java", 'String s = "http://host/path";'),
        (".sh", 'echo "# not a comment"'),
    ])
    def test_a_url_in_a_string_is_code(self, suffix, src):
        """Known-negative: replace the scanner with `'//' in line` and every
        one of these flips to comment."""
        _, (code, comment, _, _) = census_source(src, suffix)
        assert (code, comment) == (1, 0), f"{src!r} counted as comment"

    def test_a_block_comment_opener_inside_a_string_does_not_swallow_the_file(self):
        """The real damage from not tracking string literals, and the reason
        the single-line cases above are not enough.

        Those cases survive a naive scanner: `const u = "https://x"` has real
        code before the `//`, so `saw_code` wins and the line still counts as
        code. Verified by removing the quote-tracking branch — all fifteen
        tests stayed green.

        A `/*` inside a string is different in kind. Without quote tracking
        the scanner enters block-comment state and stays there, marking every
        following line as comment until it finds a `*/` that may never come.
        One string literal silently converts the rest of the file.
        """
        src = (
            'const pattern = "/* not a comment";\n'
            'doWork();\n'
            'doMore();\n'
            'andMore();\n'
        )
        _, (code, comment, _, _) = census_source(src, ".js")
        assert comment == 0, (
            f"a /* inside a string turned {comment} real code line(s) into comments"
        )
        assert code == 4

    @pytest.mark.parametrize("suffix,src", [
        (".js", "// a real comment"),
        (".java", "  /* block */"),
        (".sh", "# a real comment"),
        (".py", "# a real comment"),
    ])
    def test_a_real_comment_is_a_comment(self, suffix, src):
        """The other half — a scanner that never finds a comment would pass
        every test above."""
        _, (code, comment, _, _) = census_source(src, suffix)
        assert (code, comment) == (0, 1), f"{src!r} not counted as comment"


class TestTrailingComments:
    def test_code_with_a_trailing_comment_counts_as_code(self):
        """Defect 2. Known-negative: test `comment_lines` before `code_lines`
        in _census_python and this fails."""
        _, (code, comment, _, _) = census_source('url = "http://x"  # note', ".py")
        assert code == 1 and comment == 0

    def test_c_family_trailing_comment_counts_as_code(self):
        _, (code, comment, _, _) = census_source("x = 1; // trailing", ".js")
        assert code == 1 and comment == 0


class TestPythonCategories:
    def test_docstrings_are_separated_from_comments_and_code(self):
        src = (
            'def f():\n'
            '    """Docstring line one.\n'
            '    line two."""\n'
            '    x = 1  # trailing\n'
            '\n'
            '    # standalone\n'
            '    return x\n'
        )
        _, (code, comment, docstring, blank) = census_source(src, ".py")
        assert docstring == 2, "both docstring lines must be counted as docstring"
        assert comment == 1, "only the standalone comment is a comment"
        assert code == 3, "def, assignment-with-trailing-comment, return"
        assert blank == 1

    def test_unparseable_python_is_still_counted(self):
        """An uncountable file must not silently shrink the measured size."""
        _, (code, comment, _, blank) = census_source("def (((\nx = 1\n", ".py")
        assert code + comment > 0


class TestTree:
    def _write(self, root: Path, rel: str, text: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def test_vendored_and_build_directories_are_excluded(self, tmp_path):
        """Defect 3. Known-negative: drop _EXCLUDED_DIRS and the venv's code
        joins the project's own."""
        self._write(tmp_path, "src/app.py", "x = 1\ny = 2\n")
        self._write(tmp_path, ".venv/lib/site.py", "\n".join(f"v{i} = {i}" for i in range(50)))
        self._write(tmp_path, "node_modules/pkg/index.js", "\n".join("a();" for _ in range(50)))
        self._write(tmp_path, "build/out.py", "\n".join("b = 1" for _ in range(50)))

        census = census_tree(tmp_path)
        assert census["python"].files == 1, (
            f"only src/app.py is this project's code: {census['python'].as_dict()}"
        )
        assert census["python"].code == 2
        assert "javascript" not in census

    def test_text_only_languages_are_counted_but_never_code(self, tmp_path):
        """Markdown's `code: 0` must not read as 'no code' — nothing about it
        was categorised at all, and folding it into a code total is the
        original defect."""
        self._write(tmp_path, "README.md", "# Title\n\nSome prose.\n")
        self._write(tmp_path, "data.json", '{"a": 1}\n')
        self._write(tmp_path, "app.py", "x = 1\n")

        census = census_tree(tmp_path)
        assert census["markdown"].text_only is True
        assert census["json"].text_only is True
        assert code_line_total(census) == 1, (
            "markdown and json lines must not enter the code total"
        )

    def test_an_uncounted_suffix_is_skipped_not_guessed(self, tmp_path):
        self._write(tmp_path, "thing.zig", "const x = 1;\n")
        assert census_tree(tmp_path) == {}
