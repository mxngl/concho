"""Canonical TVD clusters: course clusters A-H (enum) with display names.

The cost DB labels every line with a free-text ``Cluster Name``. This module maps such a
label to the course cluster (by letter, by display name, or by a known legacy spelling) so
the engine and the dashboard use one canonical name per cluster. Labels that are not a
course cluster (e.g. custom clusters from ``project_config``) are kept as they are.
"""

from engines.common.config import CLUSTER_NAMES, CourseCluster

# Legacy spellings found in existing cost DBs → course cluster. "Special Contruction" is
# the typo of the AutoTVD cost_data.csv (P3.2 normalises it to "Special Construction").
LEGACY_CLUSTER_NAMES: dict[str, CourseCluster] = {
    "special contruction": CourseCluster.F,
}

_BY_KEY: dict[str, CourseCluster] = {
    **{c.value.lower(): c for c in CourseCluster},
    **{name.lower(): c for c, name in CLUSTER_NAMES.items()},
    **LEGACY_CLUSTER_NAMES,
}


def course_cluster(label: str) -> CourseCluster | None:
    """The course cluster for a cost DB label (letter, display name or legacy name)."""
    return _BY_KEY.get(" ".join(label.split()).lower())


def display_name(label: str) -> str:
    """Canonical display name for a course cluster label; other labels unchanged."""
    cluster = course_cluster(label)
    return CLUSTER_NAMES[cluster] if cluster is not None else label
