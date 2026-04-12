"""Self-improvement engine: analyzes cycle results and generates learnings."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from theswarm.domain.memory.entities import MemoryEntry, Retrospective
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope
from theswarm.domain.reporting.entities import DemoReport
from theswarm.domain.reporting.value_objects import QualityStatus

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImprovementSuggestion:
    """A concrete suggestion for improving the next cycle."""

    category: MemoryCategory
    description: str
    priority: int  # 1=high, 2=medium, 3=low
    source: str  # "quality_gate", "coverage", "cost", "pattern"


class ImprovementEngine:
    """Analyzes cycle reports and produces improvement suggestions.

    This is the "self-improvement" agent. It examines:
    - Quality gate failures/warnings
    - Test coverage trends
    - Cost patterns
    - Story completion rates
    - Recurring error patterns from memory
    """

    def analyze_report(self, report: DemoReport) -> list[ImprovementSuggestion]:
        """Analyze a single report and produce suggestions."""
        suggestions: list[ImprovementSuggestion] = []
        suggestions.extend(self._check_quality_gates(report))
        suggestions.extend(self._check_coverage(report))
        suggestions.extend(self._check_cost(report))
        suggestions.extend(self._check_completion_rate(report))
        suggestions.sort(key=lambda s: s.priority)
        return suggestions

    def generate_retrospective(
        self,
        report: DemoReport,
        suggestions: list[ImprovementSuggestion],
    ) -> Retrospective:
        """Convert suggestions into a Retrospective with MemoryEntries."""
        entries = tuple(
            MemoryEntry(
                category=s.category,
                content=s.description,
                agent="improver",
                scope=ProjectScope(project_id=report.project_id),
                cycle_date=report.created_at.strftime("%Y-%m-%d"),
            )
            for s in suggestions
        )
        return Retrospective(
            cycle_date=report.created_at.strftime("%Y-%m-%d"),
            project_id=report.project_id,
            entries=entries,
        )

    def _check_quality_gates(self, report: DemoReport) -> list[ImprovementSuggestion]:
        result = []
        for gate in report.quality_gates:
            if gate.status == QualityStatus.FAIL:
                result.append(ImprovementSuggestion(
                    category=MemoryCategory.ERRORS,
                    description=f"Quality gate '{gate.name}' failed: {gate.detail}",
                    priority=1,
                    source="quality_gate",
                ))
            elif gate.status == QualityStatus.WARN:
                result.append(ImprovementSuggestion(
                    category=MemoryCategory.IMPROVEMENTS,
                    description=f"Quality gate '{gate.name}' warning: {gate.detail}",
                    priority=2,
                    source="quality_gate",
                ))
        return result

    def _check_coverage(self, report: DemoReport) -> list[ImprovementSuggestion]:
        cov = report.summary.coverage_percent
        if cov > 0 and cov < 70:
            return [ImprovementSuggestion(
                category=MemoryCategory.IMPROVEMENTS,
                description=f"Test coverage is {cov:.1f}%, below 70% target. "
                "Add tests for uncovered modules.",
                priority=1,
                source="coverage",
            )]
        if cov > 0 and cov < 80:
            return [ImprovementSuggestion(
                category=MemoryCategory.IMPROVEMENTS,
                description=f"Test coverage is {cov:.1f}%, approaching target. "
                "Consider adding edge-case tests.",
                priority=3,
                source="coverage",
            )]
        return []

    def _check_cost(self, report: DemoReport) -> list[ImprovementSuggestion]:
        cost = report.summary.cost_usd
        if cost > 10.0:
            return [ImprovementSuggestion(
                category=MemoryCategory.IMPROVEMENTS,
                description=f"Cycle cost ${cost:.2f} exceeds $10 threshold. "
                "Consider using smaller models for simple tasks.",
                priority=2,
                source="cost",
            )]
        return []

    def _check_completion_rate(self, report: DemoReport) -> list[ImprovementSuggestion]:
        total = report.summary.stories_total
        completed = report.summary.stories_completed
        if total == 0:
            return []
        rate = completed / total
        if rate < 0.5:
            return [ImprovementSuggestion(
                category=MemoryCategory.IMPROVEMENTS,
                description=f"Only {completed}/{total} stories completed ({rate:.0%}). "
                "Consider reducing daily story count or breaking stories smaller.",
                priority=1,
                source="pattern",
            )]
        return []
