"""Flood errors without heavy imports (the Location API server imports this at start)."""


class FloodIndexError(ValueError):
    """Index build / load failure, or an index that does not match the registration. Fixed messages."""
