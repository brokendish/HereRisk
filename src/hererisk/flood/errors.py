"""Flood errors without heavy imports (the Location API server imports this at start)."""


class FloodIndexError(ValueError):
    """Index build / load failure, or an index that does not match the registration. Fixed messages."""


class DiagIndexError(ValueError):
    """The diagnosis index is missing, incomplete or does not belong to these inputs. Fixed messages."""
