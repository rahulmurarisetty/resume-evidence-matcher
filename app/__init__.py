"""Resume evidence matcher."""

__version__ = "1.0.1"

# Bumped whenever extraction, parsing or matching rules change, so stored
# results and evaluation runs can be compared across versions. Each report adds
# "-semantic" or "-exact" depending on whether matching by meaning ran for it.
# 1.0.0 changed no rule: it followed the app version. 1.0.1 changes how Claude's
# reading of a years requirement is checked; reports from the rule parser are the
# same as 1.0.0's apart from this string.
PIPELINE_VERSION = "1.0.1"


def pipeline_version(semantic: bool) -> str:
    return f"{PIPELINE_VERSION}-{'semantic' if semantic else 'exact'}"
