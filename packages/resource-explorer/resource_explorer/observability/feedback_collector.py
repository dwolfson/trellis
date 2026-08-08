"""User feedback collection — thumbs up/down after each response."""
from __future__ import annotations

from resource_explorer.observability.metrics_collector import MetricsCollector


class FeedbackCollector:
    def __init__(self) -> None:
        self.metrics = MetricsCollector()

    def prompt_and_collect(self, query_hash: str) -> None:
        """Show a simple thumbs up/down prompt and record the result."""
        try:
            from rich.prompt import Prompt
            answer = Prompt.ask("Was this helpful?", choices=["y", "n", ""], default="")
            if answer == "y":
                self.metrics.record_feedback(query_hash, 1)
            elif answer == "n":
                self.metrics.record_feedback(query_hash, -1)
        except (KeyboardInterrupt, EOFError):
            pass
