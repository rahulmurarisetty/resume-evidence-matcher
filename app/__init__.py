"""Resume evidence matcher."""

__version__ = "1.0.0"

# Bumped whenever extraction, parsing or matching rules change, so stored
# results and evaluation runs can be compared across versions. Each report adds
# "-semantic" or "-exact" depending on whether matching by meaning ran for it.
# 1.0.0 changes no rule: it follows the app version, and its reports are the
# same as 0.5.0's apart from this string.
PIPELINE_VERSION = "1.0.0"


def pipeline_version(semantic: bool) -> str:
    return f"{PIPELINE_VERSION}-{'semantic' if semantic else 'exact'}"
