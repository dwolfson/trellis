#!/usr/bin/env python3
"""
Generate question_spec annotations for Egeria report specs.

For each FormatSet with question_spec: null, uses an LLM to:
  1. Select the most relevant user perspectives from the configured list
  2. Generate natural language questions each perspective might ask

Results are written back to a JSON file compatible with pyegeria's
load_user_report_specs() mechanism.

Usage:
    python scripts/generate_question_specs.py
    python scripts/generate_question_specs.py --dry-run
    python scripts/generate_question_specs.py --resume
    python scripts/generate_question_specs.py --output config/report_specs_annotated.json
    python scripts/generate_question_specs.py --spec "Glossary-DrE-Basic"
"""

import sys
import json
import argparse
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import requests
from loguru import logger


# --- Configuration ---

SPECS_INPUT = Path("data/repos/egeria-python/config/report_specs.json")
SPECS_OUTPUT = Path("config/report_specs_annotated.json")
CONFIG_PATH = Path("config/advisor.yaml")
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"
TEMPERATURE = 0.3
TIMEOUT = 120


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def load_specs(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def save_specs(specs: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(specs, f, indent=2)


def get_column_names(spec: dict) -> list[str]:
    names = []
    for fmt in spec.get("formats", []):
        for attr in fmt.get("attributes", []):
            name = attr.get("name")
            if name and name not in names:
                names.append(name)
    return names[:15]  # cap to keep prompt concise


def build_prompt(spec_name: str, spec: dict, perspectives: list[str]) -> str:
    target_type = spec.get("target_type") or spec_name.split("-")[0].replace("-", " ")
    family = spec.get("family", "General")
    description = spec.get("description", "")
    columns = get_column_names(spec)
    tier = "Basic" if spec_name.endswith("-Basic") else "Advanced" if spec_name.endswith("-Advanced") else ""

    return f"""You are helping annotate Egeria metadata management report specifications.

Report spec details:
- Name: {spec_name}
- Target Type: {target_type}
- Family: {family}
- Tier: {tier or "Standard"}
- Description: {description}
- Key attributes: {", ".join(columns)}

Available user perspectives:
{chr(10).join(f"  - {p}" for p in perspectives)}

Task:
1. Select 2-4 perspectives from the list above that would most naturally use this report in their day-to-day work.
2. For each selected perspective, write 2-3 concise natural language questions this report could answer for them.

Rules:
- Only select perspectives with a genuine reason to use this specific report type.
- Questions should sound like something a real user would type, not a database query.
- Keep questions short (under 15 words each).
- Do not include perspectives that have no plausible connection to {target_type}.

Respond with valid JSON only, no explanation, no markdown fences:
[
  {{
    "perspectives": ["Perspective Name"],
    "questions": ["Question one?", "Question two?"]
  }}
]"""


def call_ollama(prompt: str, model: str = MODEL) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": 512,
        }
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json().get("response", "").strip()


def parse_question_spec(raw: str) -> list[dict] | None:
    """Extract and validate JSON array from LLM response."""
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Find first '[' to handle any leading text
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return None

    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list):
        return None

    result = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        perspectives = item.get("perspectives", [])
        questions = item.get("questions", [])
        if not perspectives or not questions:
            continue
        result.append({
            "perspectives": [str(p) for p in perspectives],
            "questions": [str(q) for q in questions]
        })

    return result if result else None


def main():
    parser = argparse.ArgumentParser(description="Generate question_spec for report specs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show prompts without calling LLM")
    parser.add_argument("--resume", action="store_true",
                        help="Skip specs that already have question_spec in output file")
    parser.add_argument("--output", type=Path, default=SPECS_OUTPUT,
                        help=f"Output file (default: {SPECS_OUTPUT})")
    parser.add_argument("--spec", type=str, default=None,
                        help="Process a single spec by name")
    parser.add_argument("--model", type=str, default=MODEL,
                        help=f"Ollama model to use (default: {MODEL})")
    args = parser.parse_args()

    model = args.model

    # Load inputs
    config = load_config()
    perspectives = config.get("egeria_user_perspectives", [])
    if not perspectives:
        logger.error("No perspectives found in config/advisor.yaml under egeria_user_perspectives")
        sys.exit(1)

    specs = load_specs(SPECS_INPUT)
    logger.info(f"Loaded {len(specs)} report specs from {SPECS_INPUT}")
    logger.info(f"Loaded {len(perspectives)} perspectives from config")

    # Load existing output for resume mode
    existing: dict = {}
    if args.resume and args.output.exists():
        existing = load_specs(args.output)
        logger.info(f"Resume mode: loaded {len(existing)} existing annotated specs")

    # Filter to specs needing annotation
    if args.spec:
        if args.spec not in specs:
            logger.error(f"Spec not found: {args.spec}")
            sys.exit(1)
        to_process = {args.spec: specs[args.spec]}
    else:
        to_process = {
            k: v for k, v in specs.items()
            if v.get("question_spec") is None
            and not (args.resume and k in existing and existing[k].get("question_spec"))
        }

    logger.info(f"Specs to annotate: {len(to_process)}")

    if args.dry_run:
        k, v = next(iter(to_process.items()))
        print(f"\n--- DRY RUN: sample prompt for '{k}' ---\n")
        print(build_prompt(k, v, perspectives))
        print(f"\n--- Would process {len(to_process)} specs total ---")
        return

    # Check Ollama is available
    try:
        requests.get("http://localhost:11434/api/tags", timeout=5).raise_for_status()
    except Exception:
        logger.error("Ollama is not available at localhost:11434")
        sys.exit(1)

    # Start with existing annotated specs, add to them
    output_specs = dict(existing)

    success = 0
    failed = 0

    for i, (spec_name, spec) in enumerate(to_process.items(), 1):
        logger.info(f"[{i}/{len(to_process)}] Annotating: {spec_name}")

        prompt = build_prompt(spec_name, spec, perspectives)

        try:
            raw = call_ollama(prompt, model=model)
            question_spec = parse_question_spec(raw)

            if question_spec:
                annotated = dict(spec)
                annotated["question_spec"] = question_spec
                output_specs[spec_name] = annotated
                success += 1
                logger.info(f"  ✓ {len(question_spec)} perspective group(s)")
                for qs in question_spec:
                    logger.info(f"    {qs['perspectives']}: {len(qs['questions'])} questions")
            else:
                logger.warning(f"  ✗ Could not parse response for {spec_name}")
                logger.debug(f"  Raw response: {raw[:200]}")
                output_specs[spec_name] = spec  # keep original
                failed += 1

        except Exception as e:
            logger.error(f"  ✗ Failed: {e}")
            output_specs[spec_name] = spec
            failed += 1

        # Save incrementally every 10 specs
        if i % 10 == 0:
            save_specs(output_specs, args.output)
            logger.info(f"  Checkpoint saved ({i} processed)")

        # Brief pause to avoid hammering Ollama
        time.sleep(0.5)

    # Final save
    save_specs(output_specs, args.output)

    logger.info(f"\nDone. Success: {success}, Failed: {failed}")
    logger.info(f"Output written to: {args.output}")
    logger.info("To load into pyegeria, set PYEGERIA_USER_REPORT_SPECS_DIR to the output directory")


if __name__ == "__main__":
    main()
