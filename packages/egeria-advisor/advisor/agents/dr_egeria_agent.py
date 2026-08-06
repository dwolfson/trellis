"""
Dr. Egeria Action Agent.

Handles write/action queries by:
1. Finding the appropriate Dr. Egeria command template
2. Extracting parameters from the user request via LLM
3. Composing a complete Dr. Egeria markdown file
4. Executing it in-process via md_processing's v2 command dispatcher

All public methods are synchronous to match the RAGSystem dispatch pattern.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger


# ---------------------------------------------------------------------------
# Dr.Egeria markdown execution — in-process, no MCP
# ---------------------------------------------------------------------------
#
# pyegeria's MCP server (pyegeria.core.mcp_server, >=6.0.16) was scoped down to
# report-only tools (list_reports/find_report_specs/describe_report/run_report/
# prompt) — the "dr_egeria_run_block" tool it used to expose no longer exists
# in any locally available pyegeria build. Dr.Egeria command execution now
# lives only as an in-process engine (md_processing.v2's UniversalExtractor +
# V2Dispatcher), with no MCP wrapper; the standalone `dr_egeria`/`dr_egeria_md`
# CLI (commands.cat.dr_egeria:process_markdown_file) is a thin, file-based,
# rich-console-output shim over the same engine. This calls the engine
# directly instead, building the same {success, output, validation_errors,
# execution_errors, commands_total, commands_succeeded, commands_failed,
# commands_detail} envelope governance_plan_agent._parse_dr_egeria_response()
# has always expected. See docs/PROJECT_SUMMARY.md Phase 25.

async def _execute_dr_egeria_markdown(
    markdown: str, directive: str, conn: Dict[str, str]
) -> Dict[str, Any]:
    import uuid

    from md_processing.dr_egeria import setup_dispatcher
    from md_processing.v2 import UniversalExtractor
    from pyegeria import EgeriaTech

    client = EgeriaTech(conn["server_name"], conn["url"], conn["user_id"], conn["user_pass"])
    client.create_egeria_bearer_token()

    commands = UniversalExtractor(markdown).extract_commands()
    dispatcher = setup_dispatcher(client)
    context = {"directive": directive, "request_id": str(uuid.uuid4())}
    results = await dispatcher.dispatch_batch(commands, context)

    commands_detail: List[Dict[str, Any]] = []
    validation_errors: List[Dict[str, Any]] = []
    execution_errors: List[Dict[str, Any]] = []
    outputs: List[str] = []
    step = 0
    succeeded = 0
    failed = 0

    for res in results:
        if res.get("output"):
            outputs.append(str(res["output"]))
        if not res.get("is_command", True):
            continue
        step += 1
        status = res.get("status", "unknown")
        command_name = f"{res.get('verb', '')} {res.get('object_type', '')}".strip()
        message = res.get("message", "")
        commands_detail.append({
            "step": step,
            "command": command_name,
            "status": status,
            "guid": res.get("guid") or "",
            "qualified_name": res.get("qualified_name") or "",
            "display_name": res.get("display_name") or "",
            "message": message,
        })
        if status == "success":
            succeeded += 1
        elif status == "failure":
            failed += 1
            execution_errors.append({"step": step, "command": command_name, "message": message})
        for err in res.get("errors", []) or []:
            validation_errors.append({"step": step, "command": command_name, "message": err})

    return {
        "success": failed == 0,
        "output": "\n\n".join(outputs),
        "validation_errors": validation_errors,
        "execution_errors": execution_errors,
        "commands_total": step,
        "commands_succeeded": succeeded,
        "commands_failed": failed,
        "commands_detail": commands_detail,
    }


# ---------------------------------------------------------------------------
# Template index — built from file system on first use
# ---------------------------------------------------------------------------

class TemplateIndex:
    """
    Lightweight in-memory index of Dr. Egeria command templates.

    Indexed from:
      data/repos/egeria-python/sample-data/templates/basic/
      data/repos/egeria-python/sample-data/templates/advanced/

    Each entry maps a normalised command name → (file_path, tier, family, command_name).
    """

    def __init__(self, base_paths: Optional[List[str]] = None):
        self._entries: List[Dict[str, str]] = []  # {name, family, tier, file_path}
        self._loaded = False
        self._base_paths = base_paths

    def _default_base_paths(self) -> List[Path]:
        """Find template base paths, deduplicating by resolved path."""
        candidates = []
        # Repo path from config (primary)
        try:
            from advisor.config import get_full_config
            cfg = get_full_config()
            ds = cfg.get("data_sources")
            if ds and hasattr(ds, "egeria_python_path"):
                p = Path(str(ds.egeria_python_path)) / "sample-data" / "templates"
                candidates.append(p)
        except Exception:
            pass

        # Fallback: data/repos relative path
        repo_path = Path(__file__).parent.parent.parent / "data" / "repos" / "egeria-python" / "sample-data" / "templates"
        candidates.append(repo_path)

        # Deduplicate by resolved path; use first existing match only
        seen: set = set()
        result = []
        for p in candidates:
            if not p.exists():
                continue
            resolved = str(p.resolve())
            if resolved not in seen:
                seen.add(resolved)
                result.append(p)
                break  # one source is enough to avoid duplicates
        return result

    def load(self) -> None:
        if self._loaded:
            return

        if self._base_paths:
            bases = [Path(p) for p in self._base_paths if Path(p).exists()]
        else:
            bases = self._default_base_paths()

        if not bases:
            logger.warning("No template base paths found — DrEgeriaActionAgent template index empty")
            self._loaded = True
            return

        for base in bases:
            for tier_dir in base.iterdir():
                if not tier_dir.is_dir():
                    continue
                tier = tier_dir.name.lower()  # "basic" or "advanced"
                for family_dir in tier_dir.iterdir():
                    if not family_dir.is_dir():
                        continue
                    family = family_dir.name
                    for md_file in family_dir.glob("*.md"):
                        command_name = _file_to_command_name(md_file.name)
                        self._entries.append({
                            "command_name": command_name,
                            "family": family,
                            "tier": tier,
                            "file_path": str(md_file),
                        })

        logger.info(f"TemplateIndex loaded {len(self._entries)} templates from {[str(b) for b in bases]}")
        self._loaded = True

    def find(self, query: str, prefer_basic: bool = True) -> List[Dict[str, str]]:
        """
        Find templates matching query keywords.

        Returns a list of matching entries sorted by relevance (required fields first,
        basic tier preferred by default).
        """
        self.load()
        if not self._entries:
            return []

        query_lower = query.lower()
        # Keep action verbs (create, add, link, etc.) since they appear in template names.
        # Only strip generic filler words.
        stop = {"a", "an", "the", "some", "my", "our", "for", "in", "to", "of",
                "with", "called", "named", "new", "please", "can", "you", "i",
                "would", "like", "want", "need", "help", "me", "us"}
        keywords = [
            w.strip("?.,!") for w in query_lower.split()
            if w.strip("?.,!") not in stop and len(w.strip("?.,!")) > 2
        ]

        # Use first 3 keywords for command-name matching (action + entity only).
        # Only match against template command names, not families, to avoid noise
        # from context words in the user's parameter values.
        intent_keywords = keywords[:3]

        scored = []
        for entry in self._entries:
            name_lower = entry["command_name"].lower()
            score = 0
            for kw in intent_keywords:
                if kw in name_lower:
                    idx = name_lower.find(kw)
                    position_bonus = 2 if idx < 15 else 1
                    score += position_bonus
            # Coverage bonus: fraction of significant template name words found in the query
            name_words = [w for w in name_lower.split() if len(w) > 3]
            coverage = sum(1 for w in name_words if w in query_lower) / max(len(name_words), 1)
            score += coverage * 0.5
            if score > 0.1:
                tier_bonus = 1 if (prefer_basic and entry["tier"] == "basic") else 0
                scored.append((score + tier_bonus, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored]

    def get_by_name(self, command_name: str, tier: str = "basic") -> Optional[Dict[str, str]]:
        """Get a template entry by exact command name (case-insensitive)."""
        self.load()
        name_lower = command_name.lower()
        tier_lower = tier.lower()
        # Exact match, tier preferred
        for entry in self._entries:
            if entry["command_name"].lower() == name_lower and entry["tier"] == tier_lower:
                return entry
        # Any tier
        for entry in self._entries:
            if entry["command_name"].lower() == name_lower:
                return entry
        return None


def _file_to_command_name(filename: str) -> str:
    """Convert 'Create_Glossary_Term.md' → 'Create Glossary Term'."""
    return filename.replace(".md", "").replace("_", " ")


# ---------------------------------------------------------------------------
# Template parsing
# ---------------------------------------------------------------------------

def parse_template(file_path: str) -> Dict[str, Any]:
    """
    Parse a Dr. Egeria template file into a structured dict.

    Returns:
      {
        "command_name": "Create Glossary",
        "description": "...",
        "attributes": [
          {"name": "Display Name", "required": True, "type": "Simple",
           "description": "...", "valid_values": [...], "default_value": "..."},
          ...
        ]
      }
    """
    text = Path(file_path).read_text(encoding="utf-8")
    lines = text.splitlines()

    result: Dict[str, Any] = {"command_name": "", "description": "", "attributes": []}
    current_attr: Optional[Dict[str, Any]] = None

    for line in lines:
        stripped = line.strip()

        # Command header: ## Create Glossary
        if stripped.startswith("## ") and not result["command_name"]:
            result["command_name"] = stripped[3:].strip()
            continue

        # Description line after command (before any attribute is started)
        if stripped.startswith(">") and result["command_name"] and current_attr is None:
            desc_text = stripped.lstrip("> ").strip()
            if not desc_text.startswith("**"):
                if result["description"]:
                    result["description"] += " " + desc_text
                else:
                    result["description"] = desc_text
            continue

        # Attribute header: ### Display Name
        if stripped.startswith("### "):
            if current_attr:
                result["attributes"].append(current_attr)
            current_attr = {
                "name": stripped[4:].strip(),
                "required": False,
                "type": "Simple",
                "description": "",
                "valid_values": [],
                "default_value": None,
                "alternative_labels": [],
            }
            continue

        if current_attr is None:
            continue

        # Attribute metadata lines: > **Input Required**: True
        m = re.match(r"^>\s*\*\*Input Required\*\*:\s*(.+)", stripped)
        if m:
            current_attr["required"] = m.group(1).strip().lower() == "true"
            continue

        m = re.match(r"^>\s*\*\*Attribute Type\*\*:\s*(.+)", stripped)
        if m:
            current_attr["type"] = m.group(1).strip()
            continue

        m = re.match(r"^>\s*\*\*Description\*\*:\s*(.+)", stripped)
        if m:
            current_attr["description"] = m.group(1).strip()
            continue

        m = re.match(r"^>\s*\*\*Valid Values\*\*:\s*(.+)", stripped)
        if m:
            current_attr["valid_values"] = [v.strip() for v in m.group(1).split(",")]
            continue

        m = re.match(r"^>\s*\*\*Default Value\*\*:\s*(.+)", stripped)
        if m:
            current_attr["default_value"] = m.group(1).strip()
            continue

        m = re.match(r"^>\s*\*\*Alternative Labels\*\*:\s*(.+)", stripped)
        if m:
            current_attr["alternative_labels"] = [
                v.strip().strip('"') for v in m.group(1).split(";")
            ]
            continue

    if current_attr:
        result["attributes"].append(current_attr)

    return result


# ---------------------------------------------------------------------------
# Command composition
# ---------------------------------------------------------------------------

def compose_command(template: Dict[str, Any], params: Dict[str, Any]) -> str:
    """
    Compose a Dr. Egeria markdown command block from template + extracted params.

    Only includes attributes that have a value in params.
    Returns a complete file with ___ delimiters.
    """
    lines = ["___", "", f"## {template['command_name']}", ""]
    for attr in template["attributes"]:
        attr_name = attr["name"]
        value = params.get(attr_name) or params.get(attr_name.lower())
        # Also check aliases
        if value is None:
            for alias in attr.get("alternative_labels", []):
                if alias and alias.lower() in {k.lower() for k in params}:
                    for k, v in params.items():
                        if k.lower() == alias.lower():
                            value = v
                            break
                    if value is not None:
                        break
        if value is not None:
            lines.append(f"### {attr_name}")
            if isinstance(value, list):
                for v in value:
                    lines.append(f"> {v}")
            else:
                lines.append(f"> {value}")
            lines.append("")
    lines += ["___", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main agent class
# ---------------------------------------------------------------------------

class DrEgeriaActionAgent:
    """
    Agent for handling Dr. Egeria write/action requests.

    Usage:
        agent = DrEgeriaActionAgent()
        result = agent.handle("Create a glossary called Business Terms for our data stewards")
    """

    def __init__(self, config_path: str = "config/mcp_servers.json"):
        self._config_path = config_path
        self._template_index = TemplateIndex()
        self._egeria_conn: Optional[Dict[str, str]] = None  # lazy

    def _get_egeria_conn(self, egeria_credentials: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Extract Egeria connection params for Dr.Egeria command execution.

        url/server_name are static — same Egeria instance for everyone — resolved
        via advisor.mcp_config.get_pyegeria_platform_config() (env vars first,
        then config/mcp_servers.json) and cached on self. user_id/user_pass are
        resolved FRESH on every call from the caller's own credentials (see
        advisor.auth.resolve_egeria_credentials) and are NEVER cached on self:
        this class is a process-wide singleton (get_dr_egeria_agent()) shared
        across every user's requests, so caching credentials here would leak the
        first caller's identity into every subsequent user's actions for the
        life of the process.
        """
        if self._egeria_conn is None:
            from advisor.mcp_config import get_pyegeria_platform_config
            conn = get_pyegeria_platform_config(self._config_path)
            self._egeria_conn = {
                "url": conn["platform_url"] or "https://localhost:9443",
                "server_name": conn["view_server"] or "qs-view-server",
            }
        from advisor.auth import resolve_egeria_credentials
        creds = resolve_egeria_credentials(egeria_credentials)
        return {**self._egeria_conn, "user_id": creds["user_id"], "user_pass": creds["password"]}

    def find_template(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Find and parse the best matching template for this query.

        Returns the parsed template dict, or None if nothing suitable found.
        """
        matches = self._template_index.find(query, prefer_basic=True)
        if not matches:
            return None
        best = matches[0]
        try:
            return parse_template(best["file_path"])
        except Exception as e:
            logger.warning(f"Failed to parse template {best['file_path']}: {e}")
            return None

    @staticmethod
    def _normalize_key(k: str) -> str:
        return k.lower().replace("_", " ").replace("-", " ").strip()

    def _normalize_params(self, raw: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Re-key LLM output so keys match template attribute names exactly.

        The LLM may return 'display_name' or 'Display name' when the attribute
        is called 'Display Name'. Normalise by comparing lowercase/stripped forms.
        """
        all_attrs = template["attributes"]
        # Build map: normalised-key → canonical attribute name
        norm_to_canon: Dict[str, str] = {}
        for a in all_attrs:
            norm_to_canon[self._normalize_key(a["name"])] = a["name"]
            for alias in a.get("alternative_labels", []):
                if alias:
                    norm_to_canon[self._normalize_key(alias)] = a["name"]

        result: Dict[str, Any] = {}
        for k, v in raw.items():
            canon = norm_to_canon.get(self._normalize_key(k))
            result[canon if canon else k] = v
        return result

    def _regex_pre_extract(self, query: str, template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fast regex extraction for common patterns before the LLM call.

        Handles: called/named "X" or called/named X (unquoted word run).
        Maps extracted value to the first required attribute with type Simple.
        """
        params: Dict[str, Any] = {}

        # Find quoted or unquoted value after "called" / "named"
        m = re.search(r'\b(?:called|named)\s+"([^"]+)"', query, re.IGNORECASE)
        if not m:
            m = re.search(r"\b(?:called|named)\s+'([^']+)'", query, re.IGNORECASE)
        if not m:
            # Unquoted: take words up to end-of-string or a sentence boundary
            m = re.search(r'\b(?:called|named)\s+([A-Za-z0-9][\w\s\-]*?)(?:\s*[.,;]|\s+(?:for|to|with|in|as|and|the)\b|$)', query, re.IGNORECASE)

        if m:
            value = m.group(1).strip().strip('"\'')
            # Target the first required Simple attribute
            for a in template["attributes"]:
                if a["required"] and a["type"] in ("Simple", "simple", ""):
                    params[a["name"]] = value
                    logger.debug(f"Regex pre-extracted {a['name']!r} = {value!r}")
                    break

        return params

    def extract_params(self, query: str, template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use LLM to extract parameter values from the user query given the template schema.

        Returns a dict of attribute_name → value (only attributes the user specified).
        """
        from advisor.llm_client import get_ollama_client
        llm = get_ollama_client()

        # Regex pre-extraction for common patterns (reliable, fast)
        pre = self._regex_pre_extract(query, template)

        required_attrs = [a for a in template["attributes"] if a["required"]]
        optional_attrs = [a for a in template["attributes"] if not a["required"]]

        def fmt_attr(a: Dict) -> str:
            s = f"- {a['name']}"
            aliases = [lb for lb in a.get("alternative_labels", []) if lb]
            if aliases:
                s += f" (also: {', '.join(aliases)})"
            s += f" (type: {a['type']}"
            if a["valid_values"]:
                s += f", valid: {','.join(a['valid_values'])}"
            if a["default_value"]:
                s += f", default: {a['default_value']}"
            s += ")"
            if a.get("description"):
                s += f": {a['description']}"
            return s

        required_list = "\n".join(fmt_attr(a) for a in required_attrs) or "(none)"
        optional_list = "\n".join(fmt_attr(a) for a in optional_attrs[:10]) or "(none)"

        # Inject pre-extracted values as hints so the LLM doesn't contradict them
        pre_hint = ""
        if pre:
            pre_hint = f"\nAlready extracted: {json.dumps(pre)}\n"

        prompt = f"""You are extracting parameters for a Dr. Egeria command from a user request.

Command: {template['command_name']}
Description: {template['description']}

Required attributes:
{required_list}

Optional attributes (provide only if clearly specified by user):
{optional_list}
{pre_hint}
User request: "{query}"

Extract ALL parameter values the user specified. Use the exact attribute names shown above as JSON keys. Return ONLY a JSON object. Do not invent values. For required attributes already extracted above, include them in the output.

JSON:"""

        try:
            response = llm.generate(prompt=prompt, temperature=0.1, max_tokens=512)
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                llm_params = self._normalize_params(json.loads(json_match.group()), template)
                # Merge: pre-extracted values win for any key they set
                merged = {**llm_params, **pre}
                return merged
        except Exception as e:
            logger.warning(f"Parameter extraction failed: {e}")

        # Fallback: regex only
        return pre

    def execute(
        self,
        markdown: str,
        directive: str = "process",
        dry_run: bool = False,
        egeria_credentials: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Execute a composed Dr.Egeria markdown file in-process via md_processing's
        v2 command dispatcher (no MCP round-trip — see _execute_dr_egeria_markdown).

        Args:
            markdown: Complete Dr.Egeria markdown command file
            directive: "display" | "validate" | "process"
            dry_run: If True, return the markdown without executing
            egeria_credentials: the authenticated caller's {user_id, password};
                falls back to the service account when None.

        Returns:
            JSON-encoded envelope string ({success, output, validation_errors,
            execution_errors, commands_total, commands_succeeded, commands_failed,
            commands_detail}) — the same shape governance_plan_agent's
            _parse_dr_egeria_response() has always expected.
        """
        if dry_run:
            return markdown

        conn = self._get_egeria_conn(egeria_credentials)

        from advisor.report_pipeline import _run_async
        envelope = _run_async(_execute_dr_egeria_markdown(markdown, directive, conn))
        return json.dumps(envelope)

    def handle(
        self,
        query: str,
        directive: str = "process",
        dry_run: bool = False,
        egeria_credentials: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Full action pipeline: find template → extract params → compose → execute.

        Args:
            query: User's natural language action request
            directive: "display" | "validate" | "process"
            dry_run: Return composed markdown without executing
            egeria_credentials: the authenticated caller's {user_id, password};
                falls back to the service account when None.

        Returns:
            Response dict compatible with RAGSystem result format.
        """
        # Step 1: Find template
        template = self.find_template(query)
        if template is None:
            return _no_template_found(query)

        command_name = template["command_name"]
        logger.info(f"Selected template: {command_name}")

        # Step 2: Extract parameters
        params = self.extract_params(query, template)
        logger.info(f"Extracted params: {list(params.keys())}")

        # Step 3: Check required params are present (normalised key comparison)
        norm_params = {self._normalize_key(k): v for k, v in params.items()}
        missing = [
            a["name"] for a in template["attributes"]
            if a["required"] and not norm_params.get(self._normalize_key(a["name"]))
        ]
        if missing:
            return {
                "query": query,
                "response": (
                    f"To **{command_name}**, I need the following required information:\n\n"
                    + "\n".join(f"- **{m}**" for m in missing)
                    + "\n\nPlease provide these details and try again."
                ),
                "query_type": "command",
                "command_name": command_name,
                "missing_params": missing,
                "sources": [],
                "num_sources": 0,
                "retrieval_time": 0.0,
                "generation_time": 0.0,
                "avg_relevance_score": 0.0,
                "context_length": 0,
            }

        # Step 4: Compose markdown
        markdown = compose_command(template, params)

        # Step 5: Execute (or dry run)
        try:
            output = self.execute(markdown, directive=directive, dry_run=dry_run,
                                   egeria_credentials=egeria_credentials)
        except Exception as e:
            logger.error(f"DrEgeria execute failed: {e}")
            output = f"Execution failed: {e}"

        response_text = output
        if dry_run:
            response_text = f"**Composed Dr. Egeria command** (not executed):\n\n```markdown\n{markdown}\n```"

        return {
            "query": query,
            "response": response_text,
            "query_type": "command",
            "command_name": command_name,
            "params_extracted": params,
            "markdown": markdown,
            "dry_run": dry_run,
            "sources": [f"Dr.Egeria template: {command_name}"],
            "num_sources": 1,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 0.0,
            "context_length": len(markdown),
        }


def _no_template_found(query: str) -> Dict[str, Any]:
    return {
        "query": query,
        "response": (
            "I couldn't find a matching Dr. Egeria command template for that request. "
            "Try phrasing your request as an action, for example: "
            "*'Create a glossary called Business Terms'* or "
            "*'Create a project called Data Governance Initiative'*."
        ),
        "query_type": "command",
        "sources": [],
        "num_sources": 0,
        "retrieval_time": 0.0,
        "generation_time": 0.0,
        "avg_relevance_score": 0.0,
        "context_length": 0,
    }


# Singleton
_dr_egeria_agent: Optional[DrEgeriaActionAgent] = None


def get_dr_egeria_agent() -> DrEgeriaActionAgent:
    global _dr_egeria_agent
    if _dr_egeria_agent is None:
        _dr_egeria_agent = DrEgeriaActionAgent()
    return _dr_egeria_agent
