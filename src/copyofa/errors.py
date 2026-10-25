"""Errors CopyOfA reports to the collector."""

from __future__ import annotations


class CopyOfAError(Exception):
    """An expected failure, reported to the collector by its message alone."""
