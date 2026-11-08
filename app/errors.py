"""Errors shared across the app. This module imports nothing from the app."""


class StartupError(RuntimeError):
    """A setting or the database stops the app from starting.

    Its message is written by the app, never quotes user data, and says what to
    change, so the logs keep it in full.
    """
