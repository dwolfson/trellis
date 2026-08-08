"""Abstract base class for all sub-surveyors."""
from __future__ import annotations

from abc import ABC, abstractmethod

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.survey_report import Annotation


class BaseSurveyor(ABC):
    """
    Each sub-surveyor inspects one aspect of a project and returns a list of
    Annotation instances.  Sub-surveyors must not import pyegeria — all Egeria
    coupling lives in EgeriaPublisher.

    Constructor receives:
        project  — the Project dataclass from the registry
        registry — open ProjectRegistry for SQLite queries
    """

    def __init__(self, project: Project, registry: ProjectRegistry) -> None:
        self.project = project
        self.registry = registry

    @property
    def step_name(self) -> str:
        """Human-readable label used as Annotation.analysis_step."""
        return self.__class__.__name__

    @abstractmethod
    def run(self) -> list[Annotation]:
        """
        Perform analysis and return zero or more Annotation instances.
        Should never raise — catch internal errors, record them via
        self._warn(), and return whatever was produced so far.
        """

    def _warn(self, results: list[Annotation], msg: str) -> None:
        """Append a RequestForAction flagging an internal survey error."""
        from resource_explorer.surveyors.survey_report import (
            RequestForActionAnnotation,
        )
        results.append(
            RequestForActionAnnotation(
                summary=f"Survey error in {self.step_name}",
                analysis_step=self.step_name,
                action_requested="Review survey configuration or data",
                action_target_name=self.project.slug,
                explanation=msg,
                confidence=0,
            )
        )
