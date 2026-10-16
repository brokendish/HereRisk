"""API data area access with path confinement and durable, no-clobber writes.

Logical layout (basic architecture 6.4)::

    <data_root>/<api_id>/work/...      records/...     dl/...  rel/...

Pipeline management code may only write to the sub-areas in ``WRITABLE_AREAS``;
``dl`` (Generation Manager) and ``rel`` / Registry (Data Publish) are never
writable from here. Path parts are validated identifiers generated internally;
``..``, absolute paths and symlinks inside the API area are rejected.

Durability: files are flushed and fsync'ed (``F_FULLFSYNC`` on macOS where
available), and parent directories are fsync'ed after entries are created or
removed. Whether the platform/filesystem honours these calls is NOT verified
here; see docs/development/phase1a1-download-fixture-usage.md.

No-overwrite: final names are created with ``os.link`` (fails if the target
exists) followed by ``unlink`` of the temporary name. ``os.rename`` silently
replaces an existing target on POSIX, so it is not used for finalisation.
"""

from __future__ import annotations

import errno
import fcntl
import os
import re
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

WRITABLE_AREAS: frozenset[tuple[str, str]] = frozenset(
    {
        ("work", "download"),
        ("work", "acquisitions"),
        ("work", "locks"),
        ("records", "configurations"),
        ("records", "acquisitions"),
        ("records", "commits"),
    }
)


class StorageError(Exception):
    """Storage failure carrying a contract error_code."""

    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(f"{error_code}: {detail}" if detail else error_code)
        self.error_code = error_code


def storage_error_code(exc: OSError) -> str:
    if exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1), errno.EFBIG):
        return "STORAGE_FULL"
    if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return "PERMISSION_DENIED"
    return "STORAGE_INTEGRITY_FAILED"


def fsync_fd(fd: int) -> None:
    if sys.platform == "darwin":
        full = getattr(fcntl, "F_FULLFSYNC", None)
        if full is not None:
            try:
                fcntl.fcntl(fd, full)
                return
            except OSError:
                pass  # e.g. filesystem without F_FULLFSYNC support: fall back
    os.fsync(fd)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        fsync_fd(fd)
    finally:
        os.close(fd)


class ApiDataArea:
    """Confined, durable file operations inside ``<data_root>/<api_id>``."""

    def __init__(self, data_root: Path, api_id: str) -> None:
        if not _PART_RE.match(api_id):
            raise ValueError("invalid api_id")
        self.data_root = Path(data_root).resolve()
        self.api_id = api_id
        self.root = self.data_root / api_id

    # -- paths ---------------------------------------------------------
    def path(self, *parts: str) -> Path:
        if len(parts) < 2 or (parts[0], parts[1]) not in WRITABLE_AREAS:
            raise StorageError("PERMISSION_DENIED", "area not writable")
        for part in parts:
            if not isinstance(part, str) or not _PART_RE.match(part) or part in (".", ".."):
                raise StorageError("PERMISSION_DENIED", "invalid path component")
        target = self.root.joinpath(*parts)
        self._reject_symlinks(target)
        return target

    def relative(self, path: Path, area: str) -> str:
        """Internal reference relative to ``<api>/<area>`` (e.g. records)."""
        return path.relative_to(self.root / area).as_posix()

    def _reject_symlinks(self, target: Path) -> None:
        current = self.data_root
        for part in target.relative_to(self.data_root).parts:
            current = current / part
            if current.is_symlink():
                raise StorageError("PERMISSION_DENIED", "symlink in data area")

    # -- directories ---------------------------------------------------
    def ensure_dir(self, path: Path) -> None:
        """Create ``path`` (and missing parents up to the API root), fsyncing parents."""
        self._reject_symlinks(path)
        if not self.data_root.is_dir():
            raise StorageError("STORAGE_INTEGRITY_FAILED", "data root missing")
        missing: list[Path] = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            try:
                os.mkdir(directory)
            except FileExistsError:
                pass
            except OSError as exc:
                raise StorageError(storage_error_code(exc)) from exc
            self._sync_dir(directory.parent)
        if not path.is_dir() or path.is_symlink():
            raise StorageError("STORAGE_INTEGRITY_FAILED", "not a directory")

    def _sync_dir(self, directory: Path) -> None:
        try:
            fsync_dir(directory)
        except OSError as exc:
            raise StorageError(storage_error_code(exc)) from exc

    def same_filesystem(self, *paths: Path) -> bool:
        devices = {os.stat(p).st_dev for p in paths}
        return len(devices) == 1

    # -- files ---------------------------------------------------------
    def open_exclusive(self, path: Path):
        """Open a new file for binary writing; fails if it exists."""
        self._reject_symlinks(path)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError as exc:
            raise StorageError("STORAGE_INTEGRITY_FAILED", "file exists") from exc
        except OSError as exc:
            raise StorageError(storage_error_code(exc)) from exc
        return os.fdopen(fd, "wb")

    def finish_file(self, handle) -> None:
        """Flush and fsync an open file, then close it."""
        try:
            handle.flush()
            fsync_fd(handle.fileno())
        except OSError as exc:
            raise StorageError(storage_error_code(exc)) from exc
        finally:
            handle.close()

    def write_new(self, path: Path, data: bytes) -> None:
        """Durably create ``path`` with ``data``; never overwrites an existing file."""
        self._reject_symlinks(path)
        if path.exists() or path.is_symlink():
            raise StorageError("STORAGE_INTEGRITY_FAILED", "file exists")
        tmp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        handle = self.open_exclusive(tmp)
        try:
            try:
                handle.write(data)
            except OSError as exc:
                handle.close()
                raise StorageError(storage_error_code(exc)) from exc
            self.finish_file(handle)
            self.link_no_clobber(tmp, path)
        finally:
            if tmp.exists():
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def link_no_clobber(self, src: Path, dst: Path) -> None:
        """Atomically give ``src`` the name ``dst`` (same FS), then drop ``src``."""
        self._reject_symlinks(src)
        self._reject_symlinks(dst)
        try:
            os.link(src, dst, follow_symlinks=False)
        except FileExistsError as exc:
            raise StorageError("STORAGE_INTEGRITY_FAILED", "target exists") from exc
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise StorageError("STORAGE_INTEGRITY_FAILED", "cross-device") from exc
            raise StorageError(storage_error_code(exc)) from exc
        self._sync_dir(dst.parent)
        try:
            os.unlink(src)
        except OSError as exc:
            raise StorageError(storage_error_code(exc)) from exc
        self._sync_dir(src.parent)

    def read_bytes(self, path: Path) -> bytes:
        self._reject_symlinks(path)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise StorageError(storage_error_code(exc)) from exc

    @contextmanager
    def exclusive_lock(self, path: Path) -> Iterator[None]:
        """Non-blocking exclusive lock bound to this process's lifetime (flock).

        Raises ``StorageError("TARGET_BUSY")`` if another holder exists. The
        kernel releases the lock if the process dies; PIDs are never used to
        steal a lock. Single-host only; shared multi-host storage is out of scope.
        """
        self._reject_symlinks(path)
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o640)
        except OSError as exc:
            raise StorageError(storage_error_code(exc)) from exc
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StorageError("TARGET_BUSY") from exc
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def remove_empty_dir(self, path: Path) -> None:
        self._reject_symlinks(path)
        try:
            os.rmdir(path)
        except OSError:
            return  # not empty or already gone: leave it
        self._sync_dir(path.parent)
