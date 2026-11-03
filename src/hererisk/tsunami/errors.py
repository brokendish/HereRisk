"""Tsunami errors without heavy imports (the Location API server imports this at start)."""

from hererisk.location.address_provider import AddressDataError


class A40FormatError(ValueError):
    """The file is not in the A40 layout this adapter knows. Fixed messages, no coordinates."""


class TsunamiIndexError(ValueError):
    """Index build / load failure, or an index that does not match the registration. Fixed messages."""


class TsunamiRegistrationError(AddressDataError):
    """The tsunami registration is malformed. Fixed messages (no paths)."""
