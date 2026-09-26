"""Project values of a TVD run, taken from ``project_config`` (P3.2).

:class:`ProjectTargets` holds everything project-specific the engine and the dashboard need:
project and team name, gross floor area, the total target and one target per cluster
(course clusters A-H by display name, then the custom clusters).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engines.common.config import (
    CLUSTER_NAMES,
    ROUNDING_AMOUNT,
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
    # Reason for accepting a mismatch outside the tolerance (tvd.target_sum_override).
    target_sum_override: str | None = None

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
            target_sum_override=tvd.target_sum_override,
        )

    @property
    def course_sum(self) -> float:
        """Sum of the course clusters A-H (all clusters that are not custom clusters)."""
        return sum(v for n, v in self.cluster_targets.items() if n not in self.custom_modes)

    def custom_clusters(self, mode: str) -> dict[str, float]:
        """Custom clusters with ``mode`` (``carved_out`` | ``on_top``) and their targets."""
        return {n: self.cluster_targets[n] for n, m in self.custom_modes.items() if m == mode}

    @property
    def carved_out_sum(self) -> float:
        """Custom clusters that are part of the total target."""
        return sum(self.custom_clusters("carved_out").values())

    @property
    def on_top_sum(self) -> float:
        """Custom clusters outside the total target (reported separately)."""
        return sum(self.custom_clusters("on_top").values())

    @property
    def gap(self) -> float:
        """(A-H + carved-out custom clusters) − total target; on-top clusters excluded."""
        return self.course_sum + self.carved_out_sum - self.total_target

    @property
    def gap_incl_on_top(self) -> float:
        """All cluster targets (incl. on-top clusters) − total target."""
        return self.gap + self.on_top_sum

    @property
    def tolerance_amount(self) -> float:
        return self.target_sum_tolerance * self.total_target

    @property
    def consistency_status(self) -> str:
        """``ok`` | ``within_tolerance`` | ``override`` | ``failed``."""
        gap = abs(self.gap)
        if gap < ROUNDING_AMOUNT:
            return "ok"
        if gap <= self.tolerance_amount:
            return "within_tolerance"
        return "override" if self.target_sum_override else "failed"

    def _gap_text(self) -> str:
        gap, total = self.gap, self.total_target
        pct = gap / total * 100 if total else 0.0
        return (
            f"course clusters A-H ({self.course_sum:,.2f}) + carved-out custom clusters "
            f"({self.carved_out_sum:,.2f}) = "
            f"{self.course_sum + self.carved_out_sum:,.2f}, gap {gap:+,.2f} "
            f"({pct:+.4f} %) vs. the total target {total:,.2f} (tolerance "
            f"{self.target_sum_tolerance:g} = {self.tolerance_amount:,.2f})"
        )

    def check(self) -> list[str]:
        """Cluster target consistency (P3.3): A-H + carved-out custom clusters must sum to
        the total target within ``target_sum_tolerance``; on-top custom clusters are outside
        the total and only reported. Raises ``ValueError`` outside the tolerance unless
        ``target_sum_override`` is set; returns notes otherwise."""
        if self.carved_out_sum > self.total_target:
            raise ValueError(
                f"carved-out custom clusters ({self.carved_out_sum:,.2f}) exceed the total "
                f"target ({self.total_target:,.2f})."
            )
        status = self.consistency_status
        if status == "failed":
            raise ValueError(
                f"cluster targets do not match the total target: {self._gap_text()}. Fix "
                "the cluster targets, mark a custom cluster as on_top, raise "
                "tvd.target_sum_tolerance, or accept the mismatch with "
                "tvd.target_sum_override (a reason)."
            )
        notes = []
        if status == "within_tolerance":
            notes.append(f"cluster targets within tolerance: {self._gap_text()}.")
        elif status == "override":
            notes.append(
                f"cluster targets outside tolerance, accepted by tvd.target_sum_override "
                f"('{self.target_sum_override}'): {self._gap_text()}."
            )
        on_top = self.custom_clusters("on_top")
        for name in sorted(on_top):
            notes.append(
                f"custom cluster '{name}' ({on_top[name]:,.2f}) is on top of "
                "the total target (not course data)."
            )
        if on_top:
            notes.append(
                f"all cluster targets incl. on-top clusters sum to "
                f"{self.total_target + self.gap_incl_on_top:,.2f}, "
                f"{self.gap_incl_on_top:+,.2f} vs. the total target {self.total_target:,.2f}."
            )
        return notes
