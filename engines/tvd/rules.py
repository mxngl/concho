"""Engine defaults of the TVD quantity aggregation (not project config, not course data).

Since P3.4 the quantity rules live in the cost DB (``quantity_rule``: ``takeoff``, ``fixed``,
``per_gsf``, ``pct_of_subtotal``, ``mirror:<AC>``, ``count_codes:<AC,...>``, and
``split_keywords``; see ``docs/engines/tvd.md``). The former AutoTVD tables (takeoff clusters,
``QUANTITY_MIRRORS``, ``TOILET_ACS``, ``AC_KEYWORD_SPLIT``) exist only in
``scripts/migrate_cost_data.py``, which turns them into cost DB rows.
"""

# Revit categories to exclude from area/length/volume aggregation
EXCLUDE_CATEGORIES = {"Furniture"}
