"""Default quantity rule tables of the TVD engine (engine defaults, not project config).

Moved from AutoTVD ``tvd_analysis.py`` in P1.3; the project values (targets, GSF, names)
that used to live next to them come from ``project_config`` since P3.2 (see
:mod:`engines.tvd.targets`). These tables move into the cost DB in P3.4
(``quantity_rule``: ``mirror:<AC>``, ``count_codes:<AC,...>``, ``split_keywords``).
They are team data, not course data.
"""

from engines.common.config import CourseCluster

# Course clusters whose cost lines use TAKEOFF quantities (A Substructure, B Shell,
# C Interiors). All other clusters fall back to Fixed Quantity only.
TAKEOFF_CLUSTERS: frozenset[CourseCluster] = frozenset(
    {CourseCluster.A, CourseCluster.B, CourseCluster.C}
)

# Revit categories to exclude from area/length/volume aggregation
EXCLUDE_CATEGORIES = {"Furniture"}

# Finish quantity mirrors: cost AC → (source takeoff AC, quantity field)
# These finishes automatically track the element they're applied to.
#   C3010 Wall Paint        = same SF as interior walls  (C1010)
#   C3020 Floor Finishes    = same SF as interior floors (B1010)
QUANTITY_MIRRORS: dict[str, tuple[str, str]] = {
    "B3010": ("B1020", "area_sf"),
    "C3010": ("C1010", "area_sf"),
    "C3020": ("B1010", "area_sf"),
}

# Keyword-based AC splitting: when one real AC covers multiple cost line items,
# use keywords (matched case-insensitively against Category + Family + Type) to
# route each takeoff element to a synthetic sub-code.
# Format: { "real_ac": [(keywords, "sub_ac"), ..., ([], "fallback_sub_ac")] }
# First match wins; an entry with an empty keyword list is the catch-all fallback.
AC_KEYWORD_SPLIT: dict[str, list[tuple[list[str], str]]] = {
    "B2010": [
        (["storefront", "curtain wall", "curtain", "glazing"], "B2010.CW"),
        ([], "B2010.PW"),   # everything else → plaster wall with framing
    ],
}

# Assembly codes that represent toilet/bathroom stall elements.
# One C1030 stall is counted per element with any of these ACs
# (counted across ALL categories, including those in EXCLUDE_CATEGORIES).
TOILET_ACS: set[str] = {"D2010"}
