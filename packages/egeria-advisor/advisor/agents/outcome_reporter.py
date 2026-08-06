"""
OutcomeReporter — verifies and documents execution results for Plan Documents.

After a Plan Document has been executed via Dr.Egeria:
  1. Maps the command families used in the plan to relevant report_specs
     (using config/governance_report_map.yaml).
  2. Runs each report via ReportPipeline, filtering with object names extracted
     from the plan.
  3. Uses the LLM to synthesise a narrative outcome summary.
  4. Composes the full Outcome section (markdown).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_report_map: Optional[Dict[str, List[str]]] = None


def _load_report_map() -> Dict[str, List[str]]:
    global _report_map
    if _report_map is not None:
        return _report_map

    cfg_path = Path(__file__).parent.parent.parent / "config" / "governance_report_map.yaml"
    try:
        with open(cfg_path) as f:
            _report_map = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning(f"OutcomeReporter: could not load report map: {exc}")
        _report_map = {}
    return _report_map


# ---------------------------------------------------------------------------
# OutcomeReporter
# ---------------------------------------------------------------------------

class OutcomeReporter:
    """
    Generates the Outcome section for an executed Plan Document.

    Typical usage:
        reporter = OutcomeReporter()
        outcome_md = reporter.generate(plan_content, execution_output, perspective)
    """

    def generate(
        self,
        plan_content: str,
        execution_output: str,
        perspective: str | None = None,
        expected_command_count: int | None = None,
        commands_succeeded: int | None = None,
        commands_failed: int | None = None,
        validation_errors: list | None = None,
        execution_errors: list | None = None,
        commands_detail: list | None = None,
        materialized_display: str = "",
        executed_by: str | None = None,
    ) -> str:
        """
        Generate a markdown Outcome section for the plan document.

        Args:
            plan_content:           Full markdown of the plan that was executed.
            execution_output:       Dr.Egeria output document (augmented plan text).
            perspective:            User's role (used to filter reports).
            expected_command_count: Commands submitted; used to detect partial execution.
            commands_succeeded:     Authoritative count from Dr.Egeria structured response.
            commands_failed:        Authoritative count from Dr.Egeria structured response.
            validation_errors:      Per-command validation failures [{step,command,message}].
            execution_errors:       Per-command runtime failures [{step,command,message}].
            commands_detail:        Per-command detail from MCP [{step,command,status,guid,
                                    qualified_name,display_name,message}].
            materialized_display:   Report/diagram output already split out per-step by
                                    GovernancePlanAgent's augmented-output parser (preferred
                                    over the regex-heuristic extraction below when given —
                                    it's precise about which content is display-only vs.
                                    part of a command's own field definitions).

        Returns:
            Markdown string for the Outcome section (ready to append to the plan).
        """
        families = self._extract_families(plan_content)
        object_names = self._extract_display_names(plan_content)
        report_specs = self._select_report_specs(families)

        if expected_command_count is None:
            expected_command_count = self._count_commands(plan_content)

        logger.info(
            f"OutcomeReporter: families={families}, "
            f"report_specs={report_specs}, objects={object_names[:5]}, "
            f"expected_commands={expected_command_count}, "
            f"succeeded={commands_succeeded}, failed={commands_failed}"
        )

        # Run verification reports
        report_results = self._run_reports(report_specs, object_names, perspective)

        # Prefer authoritative per-command detail from MCP; fall back to plan-derived list.
        if commands_detail:
            cmd_results = commands_detail  # already has status, guid, qualified_name
        else:
            cmd_results = self._build_command_results(
                plan_content,
                validation_errors or [],
                execution_errors or [],
            )

        if commands_succeeded is not None or commands_failed is not None:
            status = "Succeeded" if (commands_failed or 0) == 0 and (commands_succeeded or 0) > 0 else \
                     "Partial"   if (commands_succeeded or 0) > 0 else \
                     "Failed"
        else:
            status = self._infer_status(execution_output, expected_command_count, cmd_results)

        # Synthesise narrative — include structured errors if available
        narrative = self._synthesise_narrative(
            plan_content, execution_output, report_results, status,
            validation_errors=validation_errors or [],
            execution_errors=execution_errors or [],
        )

        return self._compose_outcome_section(
            status=status,
            narrative=narrative,
            execution_output=execution_output,
            report_results=report_results,
            cmd_results=cmd_results,
            expected_command_count=expected_command_count,
            commands_succeeded=commands_succeeded,
            commands_failed=commands_failed,
            validation_errors=validation_errors or [],
            execution_errors=execution_errors or [],
            materialized_display=materialized_display,
            executed_by=executed_by,
        )

    # ---------------------------------------------------------------------- #
    # Family extraction                                                        #
    # ---------------------------------------------------------------------- #

    def _extract_families(self, plan_content: str) -> List[str]:
        """Extract unique template families referenced in the Command Sequence."""
        families: list[str] = []

        # Look for HTML comments like <!-- Step N: Command Name\n     rationale -->
        # and also plain ## Command headers, then map command name → family.
        command_section = self._extract_command_section(plan_content)
        if not command_section:
            return families

        # Extract H2 command names
        for m in re.finditer(r'^##\s+(.+)$', command_section, re.MULTILINE):
            cmd_name = m.group(1).strip()
            family = self._command_to_family(cmd_name)
            if family and family not in families:
                families.append(family)

        return families

    def _command_to_family(self, command_name: str) -> str | None:
        """Map a Dr.Egeria command name to its template family (best guess)."""
        cn = command_name.lower()
        if "glossary" in cn:
            return "glossary"
        if "actor" in cn or "person" in cn or "team" in cn or "appointment" in cn or "profile" in cn:
            return "actor manager"
        if "collection" in cn or "folder" in cn:
            return "collections"
        if "project" in cn or "campaign" in cn:
            return "projects"
        if "governance" in cn and ("zone" in cn or "definition" in cn or
                                   "policy" in cn or "role" in cn or "driver" in cn):
            return "governance officer"
        if "data" in cn and ("field" in cn or "struct" in cn or "class" in cn or "dict" in cn):
            return "data designer"
        if "digital product" in cn:
            return "digital product manager"
        if "solution" in cn or "blueprint" in cn:
            return "solution architect"
        return None

    # ---------------------------------------------------------------------- #
    # Display name extraction (used as report search filters)                 #
    # ---------------------------------------------------------------------- #

    def _extract_display_names(self, plan_content: str) -> List[str]:
        """
        Extract the values of '### Display Name' attributes from the command sequence.
        These become the search strings for verification reports.
        """
        names: list[str] = []
        command_section = self._extract_command_section(plan_content)
        if not command_section:
            return names

        for m in re.finditer(
            r'###\s+Display Name\s*\n([^\n#<>-][^\n]*)', command_section
        ):
            val = m.group(1).strip()
            if val and "TODO" not in val and val not in names:
                names.append(val)

        return names

    def _extract_command_section(self, plan_content: str) -> str:
        """Return only the '## Command Sequence' section of a plan document.

        Stops at '## Outcome' or end of file — not at ## command-name headers.
        """
        m = re.search(
            r'^##\s+Command Sequence\s*\n(.*?)(?=^##\s+Outcome\b|\Z)',
            plan_content,
            re.MULTILINE | re.DOTALL,
        )
        return m.group(1) if m else ""

    # ---------------------------------------------------------------------- #
    # Report selection                                                         #
    # ---------------------------------------------------------------------- #

    def _select_report_specs(self, families: List[str]) -> List[str]:
        """Return deduplicated list of report_spec names for the given families."""
        report_map = _load_report_map()
        specs: list[str] = []
        for fam in families:
            fam_key = fam.lower().strip()
            for spec in report_map.get(fam_key, []):
                if spec not in specs:
                    specs.append(spec)

        if not specs:
            for spec in report_map.get("_fallback", []):
                if spec not in specs:
                    specs.append(spec)

        return specs

    # ---------------------------------------------------------------------- #
    # Report execution                                                         #
    # ---------------------------------------------------------------------- #

    def _run_reports(
        self,
        report_specs: List[str],
        object_names: List[str],
        perspective: str | None,
    ) -> Dict[str, str]:
        """
        Run each report_spec, using the first object name as a search filter.

        Returns dict: {report_spec_name → markdown_output or error_message}
        """
        results: Dict[str, str] = {}

        if not report_specs:
            return results

        try:
            from advisor.report_pipeline import get_report_pipeline
            pipeline = get_report_pipeline()
        except Exception as exc:
            logger.warning(f"OutcomeReporter: could not load report pipeline: {exc}")
            return results

        # Use first object name as search filter, or "*" for all
        search_filter = object_names[0] if object_names else "*"

        for spec in report_specs:
            try:
                result = pipeline.run_report(
                    spec,
                    search_string=search_filter,
                    page_size=50,
                )
                if result:
                    results[spec] = result
                    logger.info(f"OutcomeReporter: ran report {spec!r}")
                else:
                    logger.debug(f"OutcomeReporter: report {spec!r} returned no content")
            except Exception as exc:
                logger.warning(f"OutcomeReporter: report {spec!r} failed: {exc}")

        return results

    # ---------------------------------------------------------------------- #
    # Per-command result parsing                                               #
    # ---------------------------------------------------------------------- #

    _SUCCESS_WORDS = frozenset(("success", "created", "updated", "processed", "completed", "done", "linked", "✓"))
    _FAILURE_WORDS = frozenset(("error", "exception", "failed", "failure", "traceback", "✗", "cannot", "not found"))
    # GUIDs returned by Egeria look like 8-4-4-4-12 hex
    _GUID_RE = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.IGNORECASE)
    # Extract GUID from processor message: "Executed Verb Object (GUID: <guid>)"
    _GUID_IN_MSG_RE = re.compile(r'\(GUID:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)', re.IGNORECASE)

    def _count_commands(self, plan_content: str) -> int:
        """Count H2 command headers in the Command Sequence section of a plan."""
        section = self._extract_command_section(plan_content)
        return len(re.findall(r'^##\s+\S', section, re.MULTILINE))

    def _build_command_results(
        self,
        plan_content: str,
        validation_errors: list,
        execution_errors: list,
    ) -> List[Dict[str, str]]:
        """
        Build per-command status by combining plan command names with structured
        MCP error lists.  The MCP only reports failures; all unlisted commands
        are assumed to have succeeded — EXCEPT when an error can't be attributed
        to any specific command at all (e.g. a systemic failure like an MCP call
        timeout, surfaced as a synthetic {"step": "?", "command": "?", ...}
        entry rather than real per-command Dr.Egeria output). In that case we
        have zero evidence about what actually happened to each command, so
        fabricating an "all succeeded" table would be actively misleading —
        return [] instead and let the caller fall back to a raw-output scan.
        """
        section = self._extract_command_section(plan_content)
        cmd_names = [m.group(1).strip() for m in re.finditer(r'^##\s+(.+)$', section, re.MULTILINE)]
        if not cmd_names:
            return []

        all_errors = validation_errors + execution_errors
        unattributed = [e for e in all_errors if (e.get("command") or "").strip() in ("", "?")]
        if unattributed and len(unattributed) == len(all_errors):
            return []

        # Index errors by command name (case-insensitive)
        failed: dict[str, str] = {}
        for e in all_errors:
            key = (e.get("command") or "").strip().lower()
            if key and key != "?":
                failed[key] = e.get("message", "")

        results: List[Dict[str, str]] = []
        for name in cmd_names:
            err = failed.get(name.lower(), "")
            results.append({
                "command": name,
                "status": "Failed" if err else "Success",
                "message": err,
            })
        return results

    def _parse_command_results(self, execution_output: str) -> List[Dict[str, str]]:
        """
        Try to extract per-command success/failure from Dr.Egeria output.

        Recognises:
          - "## CommandName" or "Processing: CommandName" block headers
          - GUID presence in the output block (strong success signal)
          - Keyword-based success/failure detection

        Returns a list of {command, status, message} dicts, or [] if no structure found.
        """
        results: List[Dict[str, str]] = []

        # Split on H2-style markers that Dr.Egeria may echo back
        # Pattern: "## CommandName" or "Processing: CommandName" lines
        blocks = re.split(r'(?m)^(?:##\s+|Processing[:\s]+)(.+)$', execution_output)

        if len(blocks) < 3:
            return results

        # blocks: [pre, cmd1, body1, cmd2, body2, ...]
        for i in range(1, len(blocks) - 1, 2):
            cmd = blocks[i].strip()
            body = blocks[i + 1] if i + 1 < len(blocks) else ""
            body_lower = body.lower()
            has_guid    = bool(self._GUID_RE.search(body))
            has_success = has_guid or any(w in body_lower for w in self._SUCCESS_WORDS)
            has_failure = any(w in body_lower for w in self._FAILURE_WORDS)
            if has_failure and has_success:
                status = "Partial"
            elif has_failure:
                status = "Failed"
            elif has_success:
                status = "Success"
            else:
                status = "Unknown"
            msg = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
            results.append({"command": cmd, "status": status, "message": msg[:120]})

        return results

    # ---------------------------------------------------------------------- #
    # Status inference                                                         #
    # ---------------------------------------------------------------------- #

    def _infer_status(
        self,
        execution_output: str,
        expected_command_count: int | None = None,
        cmd_results: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        if cmd_results is None:
            cmd_results = self._parse_command_results(execution_output)

        if cmd_results:
            statuses = {r["status"] for r in cmd_results}
            # Fewer parsed results than expected = execution stopped early
            if expected_command_count and len(cmd_results) < expected_command_count:
                return "Partial"
            if statuses == {"Success"}:
                return "Success"
            if "Failed" in statuses or "Unknown" in statuses:
                if "Success" in statuses or "Partial" in statuses:
                    return "Partial"
                return "Failed"
            return "Partial"

        # No per-command structure — fall back to keyword + GUID scan
        out_lower = execution_output.lower()
        has_guid    = bool(self._GUID_RE.search(execution_output))
        has_success = has_guid or any(w in out_lower for w in self._SUCCESS_WORDS)
        has_failure = any(w in out_lower for w in self._FAILURE_WORDS)

        # If GUIDs found but also errors → partial
        if has_failure and has_success:
            return "Partial"
        if has_failure:
            return "Failed"
        if has_success:
            # Check GUID count vs expected as a rough completeness proxy
            if expected_command_count and expected_command_count > 1:
                guid_count = len(self._GUID_RE.findall(execution_output))
                if guid_count < expected_command_count:
                    return "Partial"
            return "Success"
        return "Unknown"

    # ---------------------------------------------------------------------- #
    # Narrative synthesis                                                      #
    # ---------------------------------------------------------------------- #

    def _synthesise_narrative(
        self,
        plan_content: str,
        execution_output: str,
        report_results: Dict[str, str],
        status: str,
        validation_errors: list | None = None,
        execution_errors: list | None = None,
    ) -> str:
        try:
            from advisor.llm_client import get_ollama_client
            llm = get_ollama_client()

            report_summary = ""
            for spec, content in list(report_results.items())[:3]:
                snippet = content[:400].replace("\n", " ")
                report_summary += f"\n- {spec}: {snippet}"

            error_context = ""
            for e in (validation_errors or [])[:5]:
                error_context += f"\n- VALIDATION: Step {e.get('step','?')} {e.get('command','')}: {e.get('message','')}"
            for e in (execution_errors or [])[:5]:
                error_context += f"\n- EXECUTION: Step {e.get('step','?')} {e.get('command','')}: {e.get('message','')}"

            prompt = (
                f"A governance plan was executed against Egeria with status: {status}.\n\n"
                + (f"Errors encountered:{error_context}\n\n" if error_context else "")
                + f"Verification report excerpts:{report_summary or ' (none run)'}\n\n"
                f"Write a concise 2-4 sentence outcome narrative. Describe what was created or "
                f"attempted, call out specific errors by step if present, and state the overall result. "
                f"Plain language, no bullet points."
            )
            return llm.generate(prompt, temperature=0.3, max_tokens=300)
        except Exception as exc:
            logger.warning(f"OutcomeReporter: narrative generation failed: {exc}")
            return f"Execution completed with status: {status}."

    # ---------------------------------------------------------------------- #
    # Outcome section composition                                              #
    # ---------------------------------------------------------------------- #

    def _compose_outcome_section(
        self,
        status: str,
        narrative: str,
        execution_output: str,
        report_results: Dict[str, str],
        cmd_results: Optional[List[Dict[str, str]]] = None,
        expected_command_count: int | None = None,
        commands_succeeded: int | None = None,
        commands_failed: int | None = None,
        validation_errors: list | None = None,
        execution_errors: list | None = None,
        materialized_display: str = "",
        executed_by: str | None = None,
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Completion summary line
        if commands_succeeded is not None and expected_command_count:
            completion = (
                f"   **Commands:** {commands_succeeded} of {expected_command_count} succeeded"
                + (f" ({commands_failed} failed)" if commands_failed else "")
            )
        else:
            guid_count = len(self._GUID_RE.findall(execution_output))
            completion = f"   **Objects created:** ~{guid_count}" if guid_count else ""

        executed_by_field = f"   **Executed by:** {executed_by}" if executed_by else ""

        lines = [
            "## Outcome",
            f"**Executed:** {now}   **Status:** {status}{completion}{executed_by_field}",
            "",
            "### Summary",
            "",
            narrative.strip(),
            "",
        ]

        # Structured error tables
        if validation_errors:
            lines += ["### Validation Errors", "",
                      "| Step | Command | Issue |", "|------|---------|-------|"]
            for e in validation_errors:
                lines.append(f"| {e.get('step','?')} | {e.get('command','')} | {e.get('message','')} |")
            lines.append("")

        if execution_errors:
            lines += ["### Execution Errors", "",
                      "| Step | Command | Error |", "|------|---------|-------|"]
            for e in execution_errors:
                lines.append(f"| {e.get('step','?')} | {e.get('command','')} | {e.get('message','')} |")
            lines.append("")

        # Per-command status table
        if cmd_results:
            # Detect whether we have GUID/QN data (from MCP commands_detail)
            has_guid_data = any(r.get("guid") or r.get("qualified_name") for r in cmd_results)
            rows = []
            for r in cmd_results:
                status_val = r.get("status", "success")
                failed = status_val in ("failure", "Failed")
                status_cell = "✗ Failed" if failed else "✓ Success"
                msg = r.get("message", "")

                # Show full message as Note — always useful (e.g. "Linked X to Y")
                # Truncate long messages but keep the informative part
                note = msg[:120] if msg else ""

                if has_guid_data:
                    guid = r.get("guid", "")
                    qn   = r.get("qualified_name", "")
                    # Extract GUID from message when the field is empty
                    # (happens when QN was auto-derived by Dr.Egeria, not present in plan)
                    if not guid and msg:
                        m = self._GUID_IN_MSG_RE.search(msg)
                        if m:
                            guid = m.group(1)
                    rows.append(f"| {r['command']} | {status_cell} | {guid} | {qn} | {note} |")
                else:
                    rows.append(f"| {r['command']} | {status_cell} | {note} |")
            if rows:
                if has_guid_data:
                    lines += ["### Command Results", "",
                              "| Command | Status | GUID | Qualified Name | Note |",
                              "|---------|--------|------|----------------|------|"]
                else:
                    lines += ["### Command Results", "",
                              "| Command | Status | Note |", "|---------|--------|------|"]
                lines += rows
                lines.append("")

        # Materialized report/diagram output (Mermaid diagrams, report tables) for
        # inline display. Prefer the precise per-step split from
        # GovernancePlanAgent._rebuild_command_sequence() when available; fall back
        # to the regex-heuristic extraction over the whole raw blob otherwise (e.g.
        # older callers, or a step whose command echo didn't parse). The full raw
        # output is stored separately in the plan document as a collapsible
        # "## Dr.Egeria Execution Output" section.
        dr_output = materialized_display or _extract_report_sections(execution_output)
        if dr_output:
            lines += ["### Execution Results", "", dr_output, ""]

        if report_results:
            lines += ["### Verification Reports", ""]
            for spec, content in report_results.items():
                lines += [f"#### {spec}", "", _safe_truncate(content.strip(), 3000), ""]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: extract meaningful report/diagram sections from Dr.Egeria output
# ---------------------------------------------------------------------------

# H3 field headers that are just plan field definitions — skip these blocks
_FIELD_HEADER_RE = re.compile(
    r'^### (?:Display Name|Qualified Name|Description|Status|Type Name|'
    r'Parent|Zone|Glossary|Project|Scope|Confidence|Notes?|'
    r'Role|Person|Appointment|Version|Template|Directive|'
    r'Planned|Domain|Classification|Identifier)\b',
    re.MULTILINE | re.IGNORECASE,
)

_MERMAID_BLOCK_RE = re.compile(r'```mermaid.*?```', re.DOTALL)
_TABLE_LINE_RE = re.compile(r'^\|.+\|', re.MULTILINE)


def _safe_truncate(content: str, limit: int) -> str:
    """
    Truncate `content` to at most `limit` characters without cutting a fenced
    code block (```mermaid, ```json, etc.) in half — a naive [:limit] slice can
    leave an unclosed fence, which breaks Mermaid rendering and swallows the
    rest of the document as literal code in most markdown renderers.
    """
    if len(content) <= limit:
        return content

    truncated = content[:limit]
    if truncated.count("```") % 2 == 1:
        # We cut inside an open fence. Prefer extending to the fence's actual
        # close; if the fence never closes in the source, back off to before
        # it started instead.
        close_idx = content.find("```", limit)
        if close_idx != -1:
            end = content.find("\n", close_idx)
            truncated = content[: (end if end != -1 else close_idx + 3) + 1]
        else:
            truncated = truncated[: truncated.rfind("```")]

    return truncated.rstrip() + "\n\n*(truncated)*"


def _extract_report_sections(execution_output: str) -> str:
    """
    Extract the parts of the Dr.Egeria execution output that contain new
    useful content (Mermaid diagrams, result tables, View Report output)
    rather than re-showing plan command field definitions.

    Returns a markdown string, or "" if nothing meaningful found.
    """
    if not execution_output or len(execution_output) < 50:
        return ""

    collected: list[str] = []

    # 1. Extract all Mermaid code blocks
    for m in _MERMAID_BLOCK_RE.finditer(execution_output):
        collected.append(m.group(0))

    # 2. Walk H2 sections — include a section if it contains a table or a GUID
    #    but has no field-definition H3 headers (those are plain command fields)
    guid_re = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.IGNORECASE)
    h2_sections = re.split(r'(?m)^## ', execution_output)
    for block in h2_sections[1:]:  # skip preamble before first ##
        lines = block.strip().splitlines()
        if not lines:
            continue
        header = lines[0].strip()
        body = "\n".join(lines[1:])

        # Skip command sections that are just field definitions
        if _FIELD_HEADER_RE.search(body) and not _TABLE_LINE_RE.search(body):
            continue

        # Include if body has table rows or GUIDs (report output, creation confirmations)
        has_table = bool(_TABLE_LINE_RE.search(body))
        has_guid = bool(guid_re.search(body))
        if has_table or has_guid:
            # Avoid duplicating Mermaid blocks already extracted
            body_no_mermaid = _MERMAID_BLOCK_RE.sub("", body).strip()
            if body_no_mermaid:
                collected.append(f"## {header}\n\n{body_no_mermaid}")

    if not collected:
        return ""

    # De-duplicate (Mermaid blocks might appear in both passes)
    seen: set[str] = set()
    unique: list[str] = []
    for item in collected:
        key = item[:120]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return "\n\n".join(unique)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_reporter: Optional[OutcomeReporter] = None


def get_outcome_reporter() -> OutcomeReporter:
    global _reporter
    if _reporter is None:
        _reporter = OutcomeReporter()
    return _reporter
