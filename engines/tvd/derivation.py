"""P3.5: target derivation per the course TVD workbook (``PBL_Lab_TVD-collaboration_tool.xlsx``).

Course sheets and what this module takes from them (inputs come from ``project_config``,
never from the workbook):

- ``TVD Targets`` C5:C10: budget = grant x (1 - inflation + roi) ^ (construction_year -
  grant_year) (``tvd.budget``). The team's total target (C11) stays an explicit input
  (``tvd.target``); a target above the budget is a warning.
- ``TVD Targets`` G5:J12 -> K5:K12: reference shares per cluster A-H (RSMeans SF estimate +
  previous projects, ``reference_columns``); K = mean of the references (0 if all are 0).
- ``TVD Owners``: value items per cluster rated 0-10 by several owners (``owner_ratings``);
  cluster value F = mean of all ratings of its items (blank ratings ignored); owner share
  G = F / sum of F.
- ``TVD Targets`` L5:L12: owner-adjusted share L = K x (1 - p) + G x p with
  p = ``reallocation_pct`` (``TVD Owners`` C22). The course computes the second term as
  ``G / C22 / 100`` (``TVD Owners`` H6:H20), which equals G x C22 only for C22 = 10 %; here
  L sums to 1 for every p (see ``docs/engines/tvd.md``).
- ``TVD Targets`` M5:M12: optional team adjustment M (sums to 0); N5:N12 (typed in by the
  team): the target share, L + M unless ``target_shares`` gives it explicitly.
- ``TVD Targets`` G16:N23: $ per cluster = share x total target (C11); here share x the
  course-cluster base (total target minus carved-out custom clusters; = C11 without them).

The result is the ``target_derivation`` block of the results JSON.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from engines.common.config import (
    CLUSTER_NAMES,
    Budget,
    CourseCluster,
    DeriveFromReferences,
    ExplicitSplit,
    TVDSection,
)

# Shares in the results JSON: enough decimals to recompute the amounts to the cent.
SHARE_DECIMALS = 10


def _money(x: float) -> str:
    return f"{x:,.2f}"


# --- course formulas (pure; also used by the config validation) ----------------------------


def reference_average(columns: Iterable[Mapping[str, float]]) -> dict[str, float]:
    """``TVD Targets`` K: mean of the reference shares per cluster (0 if all are 0)."""
    columns = list(columns)
    keys = list(columns[0]) if columns else []
    return {k: sum(col[k] for col in columns) / len(columns) for k in keys}


def owner_values(items: Mapping[str, Iterable[Iterable[float | None]]]) -> dict[str, float | None]:
    """``TVD Owners`` F: per cluster the mean of all ratings of all its items (blank =
    ``None`` ignored). ``None`` for a cluster without any rating."""
    out: dict[str, float | None] = {}
    for key, cluster_items in items.items():
        ratings = [r for item in cluster_items for r in item if r is not None]
        out[key] = sum(ratings) / len(ratings) if ratings else None
    return out


def owner_shares(values: Mapping[str, float | None]) -> dict[str, float]:
    """``TVD Owners`` G: cluster value / sum of all cluster values (0 without ratings)."""
    total = sum(v for v in values.values() if v is not None)
    return {k: (v / total if (v is not None and total) else 0.0) for k, v in values.items()}


def owner_adjusted(
    reference_avg: Mapping[str, float], owner_share: Mapping[str, float], reallocation_pct: float
) -> dict[str, float]:
    """``TVD Targets`` L = K x (1 - p) + G x p (intended course formula; sums to 1)."""
    p = reallocation_pct
    return {k: reference_avg[k] * (1 - p) + owner_share[k] * p for k in reference_avg}


def course_owner_term(owner_share: float, reallocation_pct: float) -> float:
    """``TVD Owners`` H as the course computes it: G / C22 / 100 (= G x C22 only for
    C22 = 10 %). Not used by the engine; documents the course formula."""
    return owner_share / reallocation_pct / 100


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
class CourseMethod:
    """Intermediate values of the course method (derive_from_references), per cluster letter."""

    reallocation_pct: float
    references: dict[str, dict[str, float]]  # column name -> cluster -> share (G-J)
    reference_average: dict[str, float]  # K
    owner_value: dict[str, float | None]  # TVD Owners F
    owner_share: dict[str, float]  # TVD Owners G
    owner_adjusted: dict[str, float]  # L
    team_adjustment: dict[str, float]  # M
    derived_share: dict[str, float]  # L + M
    final_source: str  # "L+M" | "target_shares"
    owners: list[str] = field(default_factory=list)
    item_count: dict[str, int] = field(default_factory=dict)


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
    course: CourseMethod | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def budget_amount(self) -> float | None:
        return None if self.budget is None else self.budget.amount

    @property
    def target_above_budget(self) -> bool | None:
        if self.budget is None:
            return None
        return self.total_target > self.budget.amount

    def amount(self, share: float) -> float:
        """$ for a share: share x the course-cluster base ('TVD Targets' rows 16-23)."""
        return share * self.base

    def _cluster(self, c: CourseCluster) -> dict:
        out: dict = {"name": CLUSTER_NAMES[c]}
        m = self.course
        if m is not None:
            k = c.value
            r = SHARE_DECIMALS
            ov = m.owner_value[k]
            out.update({
                "reference_shares": {n: round(col[k], r) for n, col in m.references.items()},
                "reference_average": round(m.reference_average[k], r),
                "owner_items": m.item_count.get(k, 0),
                "owner_value": None if ov is None else round(ov, r),
                "owner_share": round(m.owner_share[k], r),
                "owner_adjusted": round(m.owner_adjusted[k], r),
                "team_adjustment": round(m.team_adjustment[k], r),
                "derived_share": round(m.derived_share[k], r),
            })
        out["final_share"] = round(self.final_share[c], SHARE_DECIMALS)
        out["target"] = round(self.final_amount[c], 2)
        if m is not None:
            k = c.value
            out["amounts"] = {
                "references": {
                    n: round(self.amount(col[k]), 2) for n, col in m.references.items()
                },
                "reference_average": round(self.amount(m.reference_average[k]), 2),
                "owner_adjusted": round(self.amount(m.owner_adjusted[k]), 2),
                "team_adjustment": round(self.amount(m.team_adjustment[k]), 2),
                "derived": round(self.amount(m.derived_share[k]), 2),
            }
        return out

    def block(self) -> dict:
        """The ``target_derivation`` block of the results JSON."""
        out: dict = {
            "method": self.method,
            "budget": budget_block(self.budget),
            "total_target": round(self.total_target, 2),
            "target_above_budget": self.target_above_budget,
            "course_cluster_base": round(self.base, 2),
        }
        m = self.course
        if m is not None:
            out.update({
                "reallocation_pct": m.reallocation_pct,
                "references": list(m.references),
                "owners": list(m.owners),
                "final_source": m.final_source,
            })
        out["clusters"] = {c.value: self._cluster(c) for c in CourseCluster}
        sums = {
            "final_share": round(sum(self.final_share.values()), SHARE_DECIMALS),
            "target": round(sum(self.final_amount.values()), 2),
        }
        if m is not None:
            for key in ("reference_average", "owner_share", "owner_adjusted",
                        "team_adjustment", "derived_share"):
                sums[key] = round(sum(getattr(m, key).values()), SHARE_DECIMALS)
        out["sums"] = sums
        out["warnings"] = list(self.warnings)
        return out


def _budget_warnings(tvd: TVDSection) -> list[str]:
    if tvd.budget is None or tvd.effective_total <= tvd.budget.amount:
        return []
    return [
        f"tvd.target ({_money(tvd.effective_total)}) is above the budget from the course "
        f"formula ({_money(tvd.budget.amount)}): grant {_money(tvd.budget.grant)} x "
        f"(1 - {tvd.budget.inflation:g} + {tvd.budget.roi:g}) ^ "
        f"({tvd.budget.construction_year} - {tvd.budget.grant_year})."
    ]


def course_method(split: DeriveFromReferences) -> tuple[CourseMethod, list[str]]:
    """K, G, L, M and the target shares of the course method; plus warnings."""
    letters = [c.value for c in CourseCluster]
    references = {
        col.name: {c.value: col.shares[c] for c in CourseCluster}
        for col in split.reference_columns
    }
    k = reference_average(references.values())
    ratings = split.owner_ratings.cluster_ratings()
    values = owner_values(ratings)
    g = owner_shares(values)
    p = split.reallocation_pct
    lvals = owner_adjusted(k, g, p)
    m = {x: split.team_adjustment.get(CourseCluster(x), 0.0) for x in letters}
    derived = {x: lvals[x] + m[x] for x in letters}

    warnings = []
    unrated = [x for x in letters if values[x] is None]
    if unrated and p > 0:
        warnings.append(
            "owner_ratings: no rating for cluster(s) " + ", ".join(unrated)
            + ": owner share 0 (the course sheet would show an error)."
        )
    if split.target_shares is not None:
        source = "target_shares"
        if any(m.values()):
            warnings.append(
                "target_shares are given, so team_adjustment is only reported (derived_share "
                "= L + M), not used for the targets."
            )
    else:
        source = "L+M"
    method = CourseMethod(
        reallocation_pct=p,
        references=references,
        reference_average=k,
        owner_value=values,
        owner_share=g,
        owner_adjusted=lvals,
        team_adjustment=m,
        derived_share=derived,
        final_source=source,
        owners=list(split.owner_ratings.owners),
        item_count={x: len(ratings[x]) for x in letters},
    )
    return method, warnings


def derive_targets(tvd: TVDSection) -> TargetDerivation:
    """Cluster targets A-H from ``tvd``: an explicit split, or the course method."""
    split = tvd.cluster_split
    total = tvd.effective_total
    base = total - tvd.carved_out_total
    warnings = _budget_warnings(tvd)
    course = None
    if isinstance(split, ExplicitSplit):
        if split.basis == "amount":
            amount = {c: split.values[c] for c in CourseCluster}
            share = {c: (amount[c] / base if base else 0.0) for c in CourseCluster}
        else:  # pct of the course-cluster base
            share = {c: split.values[c] for c in CourseCluster}
            amount = {c: share[c] * base for c in CourseCluster}
    else:
        course, notes = course_method(split)
        warnings += notes
        if split.target_shares is not None:
            share = {c: split.target_shares[c] for c in CourseCluster}
        else:
            share = {c: course.derived_share[c.value] for c in CourseCluster}
        amount = {c: share[c] * base for c in CourseCluster}
    return TargetDerivation(
        method=split.method,
        total_target=total,
        base=base,
        budget=tvd.budget,
        final_share=share,
        final_amount=amount,
        course=course,
        warnings=warnings,
    )
