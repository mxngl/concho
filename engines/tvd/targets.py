"""Project values of a TVD run, taken from ``project_config`` (P3.2).

:class:`ProjectTargets` holds everything project-specific the engine and the dashboard need:
project and team name, gross floor area, the total target and one target per cluster
(course clusters A-H by display name, then the custom clusters).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engines.common.config import (
    CLUSTER_NAMES,
    CourseCluster,
    ExplicitSplit,
    ProjectConfig,
)


def _plain(x: float) -> float | int:
    """Whole numbers as int, so JSON/HTML output shows ``12500`` rather than ``12500.0``."""
    return int(x) if float(x).is_integer() else x


@dataclass(frozen=True)
class ProjectTargets:
    project_name: str
    team_name: str
    currency: str
    gross_sf: float
    total_target: float
    cluster_targets: dict[str, float]
    # Custom cluster name → "carved_out" | "on_top" (not course data).
    custom_modes: dict[str, str] = field(default_factory=dict)
    target_sum_tolerance: float = 0.001

    @classmethod
    def from_config(cls, config: ProjectConfig) -> ProjectTargets:
        tvd = config.tvd
        split = tvd.cluster_split
        if not isinstance(split, ExplicitSplit):
            raise NotImplementedError(
                "tvd.cluster_split method 'derive_from_references' is not implemented yet "
                "(roadmap P3.5); use method 'explicit'."
            )
        total = tvd.effective_total
        if split.basis == "amount":
            course = {c: split.values[c] for c in CourseCluster}
        else:  # pct of the course-cluster total (total minus carved-out custom clusters)
            base = total - tvd.carved_out_total
            course = {c: split.values[c] * base for c in CourseCluster}

        targets = {CLUSTER_NAMES[c]: _plain(v) for c, v in course.items()}
        targets.update({c.name: _plain(c.target) for c in tvd.custom_clusters})
        return cls(
            project_name=config.project.name,
            team_name=config.project.team_name,
            currency=config.project.currency,
            gross_sf=_plain(config.project.gross_sf),
            total_target=_plain(total),
            cluster_targets=targets,
            custom_modes={c.name: c.mode for c in tvd.custom_clusters},
            target_sum_tolerance=tvd.target_sum_tolerance,
        )

    def check(self) -> list[str]:
        """Consistency of the targets (course + carved-out vs. total), as in the config
        validation. Raises ``ValueError`` outside the tolerance; returns notes otherwise."""
        on_top = {n for n, m in self.custom_modes.items() if m == "on_top"}
        counted = sum(v for n, v in self.cluster_targets.items() if n not in on_top)
        diff = counted - self.total_target
        limit = self.target_sum_tolerance * self.total_target
        if abs(diff) > limit:
            raise ValueError(
                f"cluster targets (without on-top clusters) sum to {counted:,.2f}, "
                f"{abs(diff):,.2f} {'above' if diff > 0 else 'below'} the total target "
                f"{self.total_target:,.2f} (tolerance {limit:,.2f})."
            )
        notes = []
        if abs(diff) >= 0.005:
            notes.append(
                f"cluster targets differ from the total target by {diff:+,.2f} "
                f"(within tolerance {self.target_sum_tolerance:g})."
            )
        for name in sorted(on_top):
            notes.append(
                f"custom cluster '{name}' ({self.cluster_targets[name]:,.2f}) is on top of "
                "the total target (not course data)."
            )
        return notes
