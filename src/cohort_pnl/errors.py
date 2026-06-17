"""Error hierarchy for cohort-pnl fetchers."""

from __future__ import annotations


class FetcherError(Exception):
    """Base class. Catch this to handle any HL API failure."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class VenueUnavailable(FetcherError):
    """API returned an error, timed out, or returned unparseable data."""


class TokenNotListed(FetcherError):
    """Coin is not traded or not found in the response."""
