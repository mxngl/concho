"""P3.5: target derivation per the course TVD workbook (``PBL_Lab_TVD-collaboration_tool.xlsx``).

Course sheets and what this module takes from them (inputs come from ``project_config``,
never from the workbook):

- ``TVD Targets`` C5:C10: budget = grant x (1 - inflation + roi) ^ (construction_year -
  grant_year) (``tvd.budget``). The team's total target (C11) stays an explicit input
  (``tvd.target``); a target above the budget is a warning.

The result is the ``target_derivation`` block of the results JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engines.common.config import (
    CLUSTER_NAMES,
    Budget,
    CourseCluster,
    ExplicitSplit,
    TVDSection,
)

# Shares in the results JSON: enough decimals to recompute the amounts to the cent.
SHARE_DECIMALS = 10


def _money(x: float) -> str:
    return f"{x:,.2f}"


def budget_block(budget: Budget | None) -> dict | None:
    """``TVD Targets`` C5:C10: the budget inputs and the budget (C10)."""
    if budget is None:
        return None
    return {
        "grant": budget.grant,
        "grant_year": budget.grant_year,
        "construction_year": budget.construction_year,
        "years": budget.construction_year - budget.grant_year,
        "inflation": budget.inflation,
        "roi": budget.roi,
        "amount": round(budget.amount, 2),
    }


@dataclass
class TargetDerivation:
    """Cluster targets A-H of one config and how they were derived."""

    method: str
    total_target: float
    # Amount split among the course clusters A-H: total target minus carved-out custom
    # clusters (course: TVD Targets C11, no custom clusters).
    base: float
    budget: Budget | None
    final_share: dict[CourseCluster, float]
    final_amount: dict[CourseCluster, float]
    warnings: list[str] = field(default_factory=list)

    @property
    def budget_amount(self) -> float | None:
        return None if self.budget is None else self.budget.amount

    @property
    def target_above_budget(self) -> bool | None:
        if self.budget is None:
            return None
        return self.total_target > self.budget.amount

    def block(self) -> dict:
        """The ``target_derivation`` block of the results JSON."""
        return {
            "method": self.method,
            "budget": budget_block(self.budget),
            "total_target": round(self.total_target, 2),
            "target_above_budget": self.target_above_budget,
            "course_cluster_base": round(self.base, 2),
            "clusters": {
                c.value: {
                    "name": CLUSTER_NAMES[c],
                    "final_share": round(self.final_share[c], SHARE_DECIMALS),
                    "target": round(self.final_amount[c], 2),
                }
                for c in CourseCluster
            },
            "warnings": list(self.warnings),
        }


def _budget_warnings(tvd: TVDSection) -> list[str]:
    if tvd.budget is None or tvd.effective_total <= tvd.budget.amount:
        return []
    return [
        f"tvd.target ({_money(tvd.effective_total)}) is above the budget from the course "
        f"formula ({_money(tvd.budget.amount)}): grant {_money(tvd.budget.grant)} x "
        f"(1 - {tvd.budget.inflation:g} + {tvd.budget.roi:g}) ^ "
        f"({tvd.budget.construction_year} - {tvd.budget.grant_year})."
    ]


def derive_targets(tvd: TVDSection) -> TargetDerivation:
    """Cluster targets A-H from ``tvd`` (explicit split)."""
    split = tvd.cluster_split
    if not isinstance(split, ExplicitSplit):
        raise NotImplementedError(
            "tvd.cluster_split method 'derive_from_references' is not implemented yet "
            "(roadmap P3.5); use method 'explicit'."
        )
    total = tvd.effective_total
    base = total - tvd.carved_out_total
    if split.basis == "amount":
        amount = {c: split.values[c] for c in CourseCluster}
        share = {c: (amount[c] / base if base else 0.0) for c in CourseCluster}
    else:  # pct of the course-cluster base
        share = {c: split.values[c] for c in CourseCluster}
        amount = {c: share[c] * base for c in CourseCluster}
    return TargetDerivation(
        method=split.method,
        total_target=total,
        base=base,
        budget=tvd.budget,
        final_share=share,
        final_amount=amount,
        warnings=_budget_warnings(tvd),
    )
