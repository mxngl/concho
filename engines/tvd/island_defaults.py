"""Island Team 2026 project constants for the TVD engine.

temporary – replaced by project_config in P3.1/P3.2

Moved unchanged from mxngl/AutoTVD ``tvd_analysis.py`` (tag ``island-2026-final``).
These are team data, not course data. "Special Contruction" keeps the typo that
appears in the Island ``cost_data.csv`` (fixed in P3.2).
"""

# Cluster names (from cost_data.csv) that use TAKEOFF quantities.
# All other clusters fall back to Fixed Quantity only.
TAKEOFF_CLUSTERS = {"Substructure", "Shell", "Interiors"}

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

# Cluster target values (from MARQUESINA TVD worksheet — Island Team 2026).
# Keys must exactly match the "Cluster Name" column in cost_data.csv.
# Note: "Special Contruction" preserves the typo that appears in cost_data.csv.
CLUSTER_TARGETS: dict[str, float] = {
    "Substructure":              1_781_276,
    "Shell":                     3_826_446,
    "Interiors":                 2_005_842,
    "Services":                  4_041_448,
    "Equipment and Furnishings": 1_319_286,
    "Special Contruction":       1_001_839,   # typo matches cost_data.csv
    "Building Sitework":         1_435_258,
    "General Conditions":        1_294_457,
    "Equipment Rental":            400_000,
}
TOTAL_TARGET: float = 16_700_000
GROSS_SF: int = 30_000          # gross square footage for $/SF index
