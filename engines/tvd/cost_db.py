"""Cost DB parsing (AutoTVD ``cost_data.csv`` format, incl. German number format)."""


def parse_cost(val: str):
    """
    Parse cost strings, handling both EU and US number formats.
      EU: period = thousands separator, comma = decimal  → "6.251,07" → 6251.07
      US: comma  = thousands separator, period = decimal → "1,000.00" → 1000.00
    The format is detected by which separator appears last in the string.
    """
    if not val or not val.strip():
        return None
    v = val.strip().replace("$", "").replace(" ", "")
    if "," in v and "." in v:
        if v.rfind(",") > v.rfind("."):   # EU: comma is the decimal separator
            v = v.replace(".", "").replace(",", ".")
        else:                              # US: period is the decimal separator
            v = v.replace(",", "")
    elif "," in v:                         # EU with no thousands sep: "25,00"
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def load_cost_data(rows: list[dict]) -> list[dict]:
    """Parse cost data rows, skipping blank lines.

    The column names ``"Description             "`` and ``"Unit             "``
    carry trailing spaces, exactly as in the AutoTVD ``cost_data.csv`` header.
    """
    result = []
    for row in rows:
        ac = row.get("Assembly Code", "").strip()
        if not ac:
            continue
        fq_raw = row.get("Fixed Quantity", "").strip()
        result.append({
            "cluster": row.get("Cluster Name", "").strip(),
            "ac":      ac,
            "group":   row.get("Assembly Group Name", "").strip(),
            "desc":    row.get("Description             ", "").strip(),
            "unit":    row.get("Unit             ", "").strip(),
            "cost":    parse_cost(row.get("Total O&P", "")),
            "fixed_qty": float(fq_raw) if fq_raw else None,
        })
    return result
