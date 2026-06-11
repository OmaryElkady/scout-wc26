"""Text normalisation helpers shared by Python callers and SQL queries.

BigQuery `LIKE` is byte-oriented — searching for "Mbappe" never matches
"Mbappé" because `é` is two UTF-8 bytes, not one. We fold both sides to
plain ASCII before comparison so cross-script search works for every
player whose name contains diacritics (Mbappé, Rüdiger, Vinícius, Müller…).
"""
import unicodedata


def unaccent(s: str) -> str:
    """Return a copy of s with diacritics stripped and folded to lower-case.

    Uses NFKD normalisation: 'é' becomes 'e' + combining acute, then we drop
    the combining-mark category. Idempotent and safe on already-ASCII input.
    """
    if not s:
        return ""
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


# BigQuery SQL fragment that produces the same fold as Python's `unaccent`.
# Use it on the right-hand side of `LIKE` comparisons:
#     WHERE {unaccent_sql('name')} LIKE '%mbappe%'
# Both sides must be folded for the match to work.
def unaccent_sql(column_expr: str) -> str:
    """Return a BigQuery expression that lowers and strips diacritics from `column_expr`.

    Equivalent to Python's `unaccent()`. Use this whenever you build a SQL
    string and want LIKE to match across accented/unaccented variants.
    """
    return (
        f"LOWER(REGEXP_REPLACE(NORMALIZE({column_expr}, NFD), "
        r"r'\pM', ''))"
    )
