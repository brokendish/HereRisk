"""Shared Bearer token authentication for HereRisk HTTP APIs (Phase 1-G).

A deliberately small mechanism: one secret token file per API process,
managed outside Git by the OWNER, read once at startup. No users, roles,
database or OAuth.

Token file (``--auth-token-file``):

* 1 or 2 lines (2 only during a rotation), each a token of 43-128 characters
  from ``[A-Za-z0-9_-]`` (``secrets.token_urlsafe(32)`` gives 43); no duplicates
* a regular, single-link file opened without following a symlink, owned by
  the running user or root, with no group / other permissions (0600 / 0400)
* at most ``MAX_TOKEN_FILE_BYTES``

Only SHA-256 digests of the tokens are kept in memory; a presented token is
hashed and compared with every digest in constant time. Messages never
contain a token, a header value or a path.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Iterable, Mapping

MAX_TOKEN_FILE_BYTES = 4096
MAX_TOKENS = 2  # current + next, during a rotation
MIN_TOKEN_CHARS = 43
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class TokenFileError(Exception):
    """The token file is missing, untrusted or malformed. Fixed messages only."""


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


class BearerAuth:
    """Checks ``Authorization: Bearer <token>`` against the configured digests."""

    def __init__(self, digests: Iterable[bytes]) -> None:
        self._digests = tuple(digests)
        if not 1 <= len(self._digests) <= MAX_TOKENS:
            raise TokenFileError("one or two tokens are required")

    @classmethod
    def from_file(cls, path: Path) -> BearerAuth:
        return cls(_digest(t) for t in read_token_file(path))

    def check(self, headers: Mapping[str, str]) -> bool:
        """True only for exactly one well-formed ``Bearer`` credential that matches."""
        values = [v for k, v in headers.items() if k.lower() == "authorization"]
        if len(values) != 1:
            return False
        scheme, sep, token = values[0].partition(" ")
        if not sep or scheme.lower() != "bearer" or not _TOKEN_RE.match(token):
            return False
        presented = _digest(token)
        matched = False
        for digest in self._digests:  # no early exit: same work for every digest
            matched |= hmac.compare_digest(presented, digest)
        return matched


def read_token_file(path: Path) -> list[str]:
    path = Path(path)
    try:
        fd = os.open(path, _READ_FLAGS)
    except OSError as exc:
        raise TokenFileError("token file unavailable") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise TokenFileError("token file is not a single regular file")
        if st.st_uid not in (os.geteuid(), 0) or st.st_mode & 0o077:
            raise TokenFileError("token file owner / permissions not allowed")
        if st.st_size > MAX_TOKEN_FILE_BYTES:
            raise TokenFileError("token file too large")
        data = os.read(fd, MAX_TOKEN_FILE_BYTES + 1)
    finally:
        os.close(fd)
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise TokenFileError("token file is not ASCII") from exc
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # one optional final newline
    if not 1 <= len(lines) <= MAX_TOKENS or len(set(lines)) != len(lines) \
            or not all(_TOKEN_RE.match(line) for line in lines):
        raise TokenFileError("token file must hold one or two valid tokens")
    return lines


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def write_new_token_file(path: Path, *, append: bool = False) -> None:
    """Create a 0600 token file with a fresh token, or add one (rotation).

    Never prints or returns the token. Without ``append`` the file must not
    exist. With ``append`` the existing file must hold exactly one valid token;
    the new two-line file is written to a temporary 0600 file and renamed over it.
    """
    path = Path(path)
    lines = [generate_token()]
    target = path
    if append:
        existing = read_token_file(path)
        if len(existing) != 1:
            raise TokenFileError("rotation needs a file with exactly one token")
        lines = existing + lines
        target = path.with_name(f".{path.name}.tmp-{secrets.token_hex(8)}")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    try:
        os.write(fd, ("\n".join(lines) + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    if append:
        os.replace(target, path)


def remove_token(path: Path, *, keep: str) -> None:
    """Rotation step 2: keep only the ``newest`` or ``oldest`` of two tokens."""
    path = Path(path)
    existing = read_token_file(path)
    if len(existing) != 2 or keep not in ("newest", "oldest"):
        raise TokenFileError("expected a file with two tokens")
    line = existing[-1] if keep == "newest" else existing[0]
    target = path.with_name(f".{path.name}.tmp-{secrets.token_hex(8)}")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    try:
        os.write(fd, (line + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(target, path)
