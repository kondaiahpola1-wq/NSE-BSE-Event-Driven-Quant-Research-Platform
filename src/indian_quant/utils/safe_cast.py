"""Safe type casting utilities.

Handles None, NaN, comma-separated strings, and invalid values gracefully.
Used across ingestion scripts to normalize upstream data.
"""


def safe_float(val, default=None):
    """Convert value to float, handling None, NaN, strings, and commas.

    Returns default if conversion fails or value is NaN.
    """
    if val is None:
        return default
    try:
        v = float(str(val).replace(",", ""))
        return v if v == v else default  # NaN check
    except (ValueError, TypeError):
        return default


def safe_int(val, default=None):
    """Convert value to int, handling None, commas, floats, and strings.

    Returns default if conversion fails.
    """
    if val is None:
        return default
    try:
        return int(float(str(val).replace(",", "")))
    except (ValueError, TypeError):
        return default
