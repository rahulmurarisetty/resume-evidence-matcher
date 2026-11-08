"""Resume evidence matcher."""

__version__ = "0.4.0"

# Bumped whenever extraction, parsing or matching rules change, so stored
# results and evaluation runs can be compared across versions. Each report adds
# "-semantic" or "-exact" depending on whether matching by meaning ran for it.
PIPELINE_VERSION = "0.4.0"


def pipeline_version(semantic: bool) -> str:
    return f"{PIPELINE_VERSION}-{'semantic' if semantic else 'exact'}"
