"""Interactive REPL session with multi-turn conversation history."""
from __future__ import annotations

import uuid

from rich.console import Console
from rich.prompt import Confirm, Prompt

from resource_explorer.agents.conversation_agent import ConversationAgent


class InteractiveSession:
    def __init__(
        self,
        project_slug: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.console = Console()
        self.session_id = session_id or str(uuid.uuid4())
        self.project_slug = project_slug
        self._confirmed_aliases: set[str] = set()

        self.agent = ConversationAgent(project_slug=project_slug)
        self._load_history()

    def _load_history(self) -> None:
        try:
            from resource_explorer.registry import ProjectRegistry
            turns = ProjectRegistry().load_turns(self.session_id)
            if turns:
                self.agent.load_history(turns)
                self.console.print(
                    f"[dim]Resumed session {self.session_id[:8]}… "
                    f"({len(turns)} prior turns loaded)[/dim]"
                )
        except Exception:
            pass

    def _save_turn(self, query: str, response: str) -> None:
        try:
            from resource_explorer.registry import ProjectRegistry
            registry = ProjectRegistry()
            registry.append_turn(self.session_id, "user", query, self.project_slug)
            registry.append_turn(self.session_id, "assistant", response, self.project_slug)
        except Exception:
            pass

    def run(self) -> None:
        scope = f" [{self.project_slug}]" if self.project_slug else ""
        self.console.print(f"[bold]Resource Explorer{scope}[/bold] — type 'exit' to quit")
        self.console.print(f"[dim]Session: {self.session_id}[/dim]\n")
        while True:
            try:
                query = Prompt.ask("[cyan]You[/cyan]")
            except (KeyboardInterrupt, EOFError):
                break
            if query.strip().lower() in ("exit", "quit", "q"):
                break
            if not query.strip():
                continue

            effective_slug = self.project_slug
            if not effective_slug:
                effective_slug = self._check_alias(query)

            response = self.agent.handle(query, effective_slug)
            self._save_turn(query, response)
            self.console.print(f"\n[green]Assistant:[/green] {response}\n")
            import hashlib
            from resource_explorer.observability.feedback_collector import FeedbackCollector
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
            FeedbackCollector().prompt_and_collect(query_hash)

    def _check_alias(self, query: str) -> str | None:
        """Fuzzy-match the query against known projects; prompt once per novel term."""
        try:
            from resource_explorer.registry import ProjectRegistry
            registry = ProjectRegistry()
            result = registry.fuzzy_candidate(query)
            if not result:
                return None
            term, slug = result
            if term in self._confirmed_aliases:
                return slug  # already confirmed this session
            project = registry.get(slug)
            display = project.display_name if project else slug
            confirmed = Confirm.ask(
                f'Did you mean "{display}"? Remember "{term}" as an alias for {slug}?',
                default=False,
            )
            if confirmed:
                registry.add_alias(term, slug)
                self._confirmed_aliases.add(term)
                return slug
        except Exception:
            pass
        return None
