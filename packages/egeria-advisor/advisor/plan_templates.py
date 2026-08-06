"""
PlanTemplateManager — storage and retrieval of reusable Governance Plan templates.

Templates are stored as Markdown files in ~/egeria-plans/templates/.
A template is a plan document where specific values have been replaced with
{{placeholder_name}} tokens so they can be filled in for a new plan.

Example template snippet:
  ## Create Glossary
  ### Display Name
  {{glossary_name}}
  ### Description
  {{glossary_description}}

Saving a plan as a template:
  - All required field values are replaced with {{snake_case_field_name}} tokens
  - The document title becomes the template name
  - Metadata frontmatter is prepended (template_name, command_families, created)

Starting a plan from a template:
  - The template's command structure is loaded as commands_identified
  - The {{placeholders}} become the required questions in the elicitation phase
  - Q&A only covers the placeholder fields, not full decomposition
"""
from __future__ import annotations

import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _templates_path() -> Path:
    base = Path.home() / "egeria-plans"
    default = base / "plan_templates"
    try:
        cfg_file = Path(__file__).parent.parent / "config" / "advisor.yaml"
        with open(cfg_file) as f:
            cfg = yaml.safe_load(f)
        gp = cfg.get("governance_plans", {})
        p = Path(gp["plan_templates"]).expanduser() if "plan_templates" in gp else default
    except Exception:
        p = default
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:60].strip("_") or "template"


# ---------------------------------------------------------------------------
# Placeholder extraction / injection
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def extract_placeholders(content: str) -> List[str]:
    """Return all unique {{placeholder_name}} tokens found in content."""
    return list(dict.fromkeys(_PLACEHOLDER_RE.findall(content)))


def plan_to_template(plan_content: str) -> str:
    """
    Convert a completed plan document to a template by replacing field values
    under ### headings with {{snake_case_field_name}} tokens.

    Only values inside command blocks (after ## CommandName, under ### FieldName)
    are replaced. Narrative sections and the outcome section are left intact.
    """
    lines = plan_content.splitlines(keepends=True)
    result = []
    in_command_section = False
    current_field: Optional[str] = None

    for line in lines:
        stripped = line.rstrip()

        if re.match(r"^##\s+Command Sequence", stripped):
            in_command_section = True
            result.append(line)
            current_field = None
            continue

        if re.match(r"^##\s+Outcome", stripped):
            in_command_section = False
            result.append(line)
            current_field = None
            continue

        if not in_command_section:
            result.append(line)
            continue

        # Inside command section
        field_match = re.match(r"^###\s+(.+)", stripped)
        if field_match:
            current_field = field_match.group(1).strip()
            result.append(line)
            continue

        if current_field and stripped and not stripped.startswith("#") \
                and stripped != "---" and not stripped.startswith("<!--"):
            # This is a field value line — replace with placeholder
            placeholder = "{{" + re.sub(r"\s+", "_", current_field.lower()) + "}}"
            result.append(placeholder + "\n")
            current_field = None  # only replace first value line
            continue

        if stripped in ("---", ""):
            current_field = None

        result.append(line)

    return "".join(result)


# ---------------------------------------------------------------------------
# PlanTemplateManager
# ---------------------------------------------------------------------------

class PlanTemplateManager:
    """Manages reusable plan template files."""

    def __init__(self) -> None:
        self._root = _templates_path()

    def _path(self, name: str) -> Path:
        return self._root / f"{_safe_name(name)}.md"

    # ------------------------------------------------------------------
    # Save / load / delete
    # ------------------------------------------------------------------

    def save(self, name: str, plan_content: str, auto_convert: bool = True) -> str:
        """
        Save a plan as a named template.

        If auto_convert is True (default), field values are replaced with
        {{placeholders}} before saving. Pass auto_convert=False to save the
        content as-is (caller has already inserted placeholders).

        Returns the safe filename stem used on disk.
        """
        template_content = plan_to_template(plan_content) if auto_convert else plan_content

        # Prepend metadata frontmatter
        families = self._extract_command_families(plan_content)
        header = (
            f"<!-- plan_template: {name} -->\n"
            f"<!-- families: {', '.join(families)} -->\n"
            f"<!-- created: {datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n"
        )
        final = header + template_content

        safe = _safe_name(name)
        self._path(name).write_text(final, encoding="utf-8")
        logger.info(f"PlanTemplateManager: saved template '{name}' → {safe}.md")
        return safe

    def load(self, name: str) -> Optional[str]:
        """Load a template by name. Returns raw content or None."""
        p = self._path(name)
        if not p.exists():
            logger.warning(f"PlanTemplateManager: template '{name}' not found")
            return None
        return p.read_text(encoding="utf-8")

    def delete(self, name: str) -> bool:
        p = self._path(name)
        if p.exists():
            p.unlink()
            logger.info(f"PlanTemplateManager: deleted template '{name}'")
            return True
        return False

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_templates(self) -> List[Dict[str, Any]]:
        """Return metadata for all templates, newest first."""
        entries = []
        for md in sorted(self._root.glob("*.md"), reverse=True):
            content = md.read_text(encoding="utf-8", errors="replace")
            name = self._extract_meta(content, "plan_template") or md.stem.replace("_", " ").title()
            families = self._extract_meta(content, "families") or ""
            placeholders = extract_placeholders(content)
            entries.append({
                "name":         name,
                "filename":     md.stem,
                "families":     families,
                "placeholders": placeholders,
            })
        return entries

    # ------------------------------------------------------------------
    # Template → draft commands
    # ------------------------------------------------------------------

    def template_to_commands(self, name: str) -> List[Dict[str, Any]]:
        """
        Parse a template's Command Sequence section into a commands_identified list.
        Each command has action, display_name (placeholder), and placeholders dict.
        """
        content = self.load(name)
        if not content:
            return []

        commands = []
        in_cmd = False
        current_action: Optional[str] = None
        current_fields: Dict[str, str] = {}

        for line in content.splitlines():
            stripped = line.strip()

            if re.match(r"^##\s+Command Sequence", stripped):
                in_cmd = True
                continue
            if re.match(r"^##\s+Outcome", stripped):
                break
            if not in_cmd:
                continue

            # New command (## heading inside command section, but not ## Command Sequence)
            cmd_match = re.match(r"^##\s+(?!Command Sequence|Outcome)(.+)", stripped)
            if cmd_match:
                if current_action:
                    commands.append(self._build_cmd(current_action, current_fields))
                current_action = cmd_match.group(1).strip()
                current_fields = {}
                continue

            field_match = re.match(r"^###\s+(.+)", stripped)
            if field_match and current_action:
                _last_field = field_match.group(1).strip()
                continue

            if stripped and current_action and not stripped.startswith("#") \
                    and stripped != "---" and not stripped.startswith("<!--"):
                if "_last_field" in dir():
                    current_fields[_last_field] = stripped

        if current_action:
            commands.append(self._build_cmd(current_action, current_fields))

        return commands

    @staticmethod
    def _build_cmd(action: str, fields: Dict[str, str]) -> Dict[str, Any]:
        display_name = fields.get("Display Name", "")
        placeholders = {k: v for k, v in fields.items() if _PLACEHOLDER_RE.match(v)}
        return {
            "action": action,
            "display_name": display_name,
            "description": "",
            "rationale": "",
            "pre_filled": {k: v for k, v in fields.items() if not _PLACEHOLDER_RE.match(v)},
            "placeholders": placeholders,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_meta(content: str, key: str) -> Optional[str]:
        m = re.search(rf"<!--\s*{re.escape(key)}:\s*(.+?)\s*-->", content)
        return m.group(1).strip() if m else None

    @staticmethod
    def _extract_command_families(content: str) -> List[str]:
        families = []
        for m in re.finditer(r"^##\s+(?!Command Sequence|Outcome|Goal|Requirements|Approach)(.+)", content, re.MULTILINE):
            action = m.group(1).strip()
            words = action.split()
            if len(words) >= 2:
                family = words[1]  # e.g., "Create Glossary" → "Glossary"
                if family not in families:
                    families.append(family)
        return families


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tm: Optional[PlanTemplateManager] = None


def get_template_manager() -> PlanTemplateManager:
    global _tm
    if _tm is None:
        _tm = PlanTemplateManager()
    return _tm
