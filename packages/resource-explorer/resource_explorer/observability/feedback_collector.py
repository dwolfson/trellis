"""User feedback collection — thumbs up / partially correct / thumbs down
after each response."""
from __future__ import annotations

from resource_explorer.observability.metrics_collector import MetricsCollector


class FeedbackCollector:
    def __init__(self) -> None:
        self.metrics = MetricsCollector()

    def prompt_and_collect(self, query_hash: str) -> None:
        """Show a thumbs up / partial / thumbs down prompt and record the result."""
        try:
            from rich.prompt import Prompt
            answer = Prompt.ask(
                "Was this helpful? (y=yes, p=partially correct, n=no)",
                choices=["y", "p", "n", ""], default="",
            )
            if answer == "y":
                self.metrics.record_feedback(query_hash, 1)
            elif answer == "p":
                self.metrics.record_feedback(query_hash, 0)
            elif answer == "n":
                self.metrics.record_feedback(query_hash, -1)
        except (KeyboardInterrupt, EOFError):
            pass
