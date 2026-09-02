"""Sub-surveyor: File Structure → ResourceMeasureAnnotation."""
from __future__ import annotations

import logging
from collections import Counter

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.step_outcome import from_upstream_table
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ResourceMeasureAnnotation

log = logging.getLogger(__name__)

STEP = "FileStructure"


class FileStructureSurveyor(BaseSurveyor):
    """
    Produces ResourceMeasureAnnotations describing the physical shape of the repo:
      - Total file count and size from project_stats
      - Per-language file count from project_code_symbols
      - Top-level directory breakdown from indexed file paths
    """

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug

            # ── aggregate stats from project_stats ───────────────────────────
            # D2(c) (docs/repo-survey-catalog-completion-plan.md): named
            # registry accessor instead of a hand-rolled query — a third
            # confirmed instance of the same "latest project_stats row"
            # duplicate found in health.py/security_hygiene.py/language.py.
            stats = self.registry.get_latest_project_stats(slug) or {}
            file_count = stats.get("ingestion_file_count") or stats.get("file_count") or 0
            size_kb = stats.get("repo_size_kb") or 0
            # `ingestion_lines_of_code` is deliberately NOT read here any
            # more (design doc D1). It counts every newline in every
            # text-suffixed file and is named as though it counted code:
            # 1,118,195 on egeria-python against 156,902 real Python code
            # lines, 14%. Retired rather than renamed — a rename preserves a
            # number nobody should quote. The column stays in place, unread,
            # for a soak period.
            results.append(
                ResourceMeasureAnnotation(
                    check_name="repo_size",
                    summary=f"Repository contains ~{file_count:,} files, {size_kb:,} KB",
                    analysis_step=STEP,
                    resource_properties={
                        "file_count": file_count,
                        "repo_size_kb": size_kb,
                    },
                    json_properties={"source": "project_stats"},
                )
            )

            results.extend(self._code_volume_annotations(slug))

            # ── per-language breakdown from code symbols ──────────────────────
            with self.registry._conn() as conn:
                rows = conn.execute(
                    "SELECT language, COUNT(DISTINCT file_path) as file_count "
                    "FROM project_code_symbols WHERE project_slug = ? GROUP BY language ORDER BY file_count DESC",
                    (slug,),
                ).fetchall()

            # project_code_symbols is populated by repo_symbol_extraction (and,
            # historically, only by RAG ingestion). An empty table therefore
            # means "symbols were never extracted" far more often than it means
            # "this repo has no source files" — so the annotation is emitted
            # either way, labelled, instead of being silently skipped. A missing
            # annotation is the least readable of all possible outputs: it is
            # indistinguishable from the step never having run.
            lang_outcome = from_upstream_table(
                len(rows), len(rows),
                empty_table_cause="empty_code_symbols",
                no_match_cause="no_recognised_languages",
            )
            if rows:
                lang_breakdown = {r["language"]: r["file_count"] for r in rows}
                results.append(
                    ResourceMeasureAnnotation(
                        check_name="language_breakdown",
                        summary=f"Indexed source files span {len(lang_breakdown)} language(s)",
                        analysis_step=STEP,
                        resource_properties={"by_language": lang_breakdown},
                        json_properties={"source": "project_code_symbols",
                                         **lang_outcome.as_row()},
                    )
                )
            else:
                results.append(
                    ResourceMeasureAnnotation(
                        check_name="language_breakdown",
                        summary="Language breakdown unavailable — no code symbols extracted",
                        analysis_step=STEP,
                        explanation=(
                            "project_code_symbols holds no rows for this repo. Run "
                            "repo_symbol_extraction first; until then this is not "
                            "evidence that the repo has no source code."
                        ),
                        resource_properties={"by_language": {}},
                        json_properties={"source": "project_code_symbols",
                                         **lang_outcome.as_row()},
                    )
                )

            # ── top-level directory breakdown ─────────────────────────────────
            # D2(c): confirmed duplicate of security_hygiene.py's identical
            # query, now the named registry accessor.
            paths = self.registry.get_code_symbol_file_paths(slug)

            # Same table, same reasoning as the language breakdown above — but
            # left as a skip rather than an emitted zero, because it would
            # restate what that annotation has already said in the same run.
            if paths:
                top_dirs: Counter = Counter()
                for file_path in paths:
                    parts = file_path.replace("\\", "/").split("/")
                    top_dirs[parts[0] if len(parts) > 1 else "(root)"] += 1

                results.append(
                    ResourceMeasureAnnotation(
                        check_name="directory_layout",
                        summary=f"Source files distributed across {len(top_dirs)} top-level directories",
                        analysis_step=STEP,
                        resource_properties={"top_level_dirs": dict(top_dirs.most_common(20))},
                    )
                )

        except Exception as exc:
            log.exception("FileStructureSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results

    def _code_volume_annotations(self, slug: str) -> list[Annotation]:
        """Summary + per-language evidence for code volume (design doc D1).

        The decomposition Dan asked for: "the decomposition itself is
        interesting/important - it seems like these metrics are just different
        annotations that are part of the annotation type?" It is — one
        aggregate and one annotation per language, with the per-language ones
        carrying `evidence_of` so they link to the summary as real
        `AnnotationExtension` relationships (annotation-linking Phase 2).
        This is that mechanism's first consumer outside data_profiler and
        dependency, and the natural one: a per-language breakdown IS the
        evidence for an aggregate.

        Reads the `code_volume` metric written at ingestion
        (pipeline.py::_record_line_census) — the only place with the files on
        disk. Absent metric means the census never ran, which is stated
        rather than rendered as zero lines.
        """
        import json as _json

        metric = self.registry.query_metrics(slug, "code_volume") or {}
        detail = metric.get("detail")
        if isinstance(detail, str):
            detail = _json.loads(detail or "{}")
        by_language = (detail or {}).get("by_language") or {}
        if not by_language:
            return [
                ResourceMeasureAnnotation(
                    check_name="code_volume",
                    summary=("Code volume not established — no line census has been "
                             "recorded for this repository. It is written during "
                             "ingestion; a repo indexed another way has none."),
                    analysis_step=STEP,
                    resource_properties={},
                    json_properties={"source": "project_analysis_metrics:code_volume"},
                )
            ]

        counted = {k: v for k, v in by_language.items() if not v.get("text_only")}
        text_only = sorted(k for k, v in by_language.items() if v.get("text_only"))
        code = sum(v.get("code", 0) for v in counted.values())
        files = sum(v.get("files", 0) for v in counted.values())

        note = ""
        if text_only:
            # Their lines are counted and their categories are not. `code: 0`
            # for markdown must never read as "no code" — nothing about them
            # was categorised at all.
            note = (f" {', '.join(text_only)} are counted as text and excluded "
                    f"from the code total.")
        summary = ResourceMeasureAnnotation(
            check_name="code_volume",
            summary=(f"{code:,} lines of code across {files:,} source file(s) "
                     f"in {len(counted)} language(s).{note}"),
            analysis_step=STEP,
            resource_properties={
                "code_lines": code,
                "source_files": files,
                "languages": sorted(counted),
                "text_only_languages": text_only,
            },
            json_properties={"source": "project_analysis_metrics:code_volume"},
        )
        out: list[Annotation] = [summary]
        for language in sorted(counted):
            v = counted[language]
            out.append(
                ResourceMeasureAnnotation(
                    check_name="code_volume_by_language",
                    item_key=language,
                    summary=(f"{language}: {v.get('code', 0):,} code, "
                             f"{v.get('comment', 0):,} comment, "
                             f"{v.get('docstring', 0):,} docstring, "
                             f"{v.get('blank', 0):,} blank across "
                             f"{v.get('files', 0):,} file(s)."),
                    analysis_step=STEP,
                    resource_properties={"language": language, **v},
                    json_properties={"source": "project_analysis_metrics:code_volume"},
                    # Index 0 within this list is the aggregate above.
                    evidence_of=0,
                )
            )
        return out
