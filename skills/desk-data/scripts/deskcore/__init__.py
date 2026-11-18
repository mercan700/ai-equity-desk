"""deskcore: shared data layer for ai-equity-desk skills.

Every function returns small, JSON-ready dicts so Claude reads summaries,
never raw tables. Raw tables are cached on disk for other scripts to reuse.
"""


class DeskError(Exception):
    """A problem the user can fix (bad ticker, missing setup, no network)."""
