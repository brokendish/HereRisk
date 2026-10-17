"""API data area access: confinement, symlink-safe traversal, durable no-clobber writes.

Logical layout (basic architecture 6.4)::

    <data_root>/<api_id>/work/...      records/...     dl/...  rel/...

Trust boundary
--------------
* Callers never pass filesystem paths. Every operation takes a :class:`Loc`,
  a tuple of path components *relative to this API's directory*, and checks it
  against ``WRITABLE_AREAS`` (writes) or ``READABLE_AREAS`` (reads) on every call.
  A ``pathlib.Path`` is refused, so holding a path grants nothing.
* The data root is canonicalised once (at construction) and then *pinned*: it is
  opened by walking from ``/`` one component at a time with ``O_NOFOLLOW |
  O_DIRECTORY``, so a symlink swapped into the root or any ancestor before the
  pin is refused, and the (st_dev, st_ino) of every directory on the walked
  chain is recorded. Protected-root checks (:meth:`ApiDataArea.root_within`)
  and the fixture marker are evaluated on that pinned chain / fd, never by
  re-resolving the path. All traversal is relative to the pinned fd, one
  component at a time, with ``O_NOFOLLOW | O_DIRECTORY``; mkdir,
  open, link, unlink, rmdir, stat, lock and directory fsync all use ``dir_fd``.
  Replacing any directory (including parents) with a symlink after a check
  cannot redirect an operation outside the area: an operation either uses the
  directory fd already held or fails with PERMISSION_DENIED.
* Residual (documented, not prevented): a directory whose fd is already held
  can itself be *moved* elsewhere by a principal with write access to its
  parent; I/O then continues in that same directory (the pinned inode), never
  in an attacker-chosen replacement. The data area must therefore be writable
  only by the pipeline management user.
* Platforms lacking ``dir_fd`` / ``O_NOFOLLOW`` support are refused (fail safe).
* Files read back as committed evidence must be regular files owned by the
  current user with exactly one link (no external hardlink alias).

Durability: files and parent directories are fsync'ed (``F_FULLFSYNC`` on macOS
where available). Whether the platform honours this on power loss is NOT verified.

No-overwrite: final names are created with ``linkat`` (fails if the target exists)
followed by ``unlink`` of the temporary name; ``rename`` would replace a target.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import re
import stat
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

DOWNLOAD_AREAS: frozenset[tuple[str, str]] = frozenset(
    {
        ("work", "download"),
        ("work", "acquisitions"),
        ("work", "locks"),
        ("records", "configurations"),
        ("records", "acquisitions"),
        ("records", "commits"),
    }
)
# Normalize candidates and the per-run Normalize record (Phase 1-B.3-A).
NORMALIZE_AREAS: frozenset[tuple[str, str]] = frozenset(
    {
        ("work", "normalized"),
        ("records", "normalizations"),
    }
)
# Per-run Validate record (Phase 1-B.3-B). Validate writes no candidate data.
VALIDATE_AREAS: frozenset[tuple[str, str]] = frozenset({("records", "validations")})
WRITABLE_AREAS: frozenset[tuple[str, str]] = DOWNLOAD_AREAS | NORMALIZE_AREAS | VALIDATE_AREAS
# Pipeline management code only reads back evidence it wrote itself.
# dl/, rel/ and any Registry are neither readable nor writable through this class.
READABLE_AREAS: frozenset[tuple[str, str]] = frozenset(
    {
        ("work", "download"),
        ("work", "acquisitions"),
        ("records", "configurations"),
        ("records", "acquisitions"),
        ("records", "commits"),
    }
) | NORMALIZE_AREAS | VALIDATE_AREAS

PRODUCTION_DATA_ROOT = Path("/data")
FIXTURE_ROOT_MARKER = ".hererisk-fixture-data-root"
FIXTURE_ROOT_MARKER_CONTENT = b"hererisk fixture data root v1\n"

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_NEW_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_CHUNK = 64 * 1024


class StorageError(Exception):
    """Storage failure carrying a contract error_code."""

    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(f"{error_code}: {detail}" if detail else error_code)
        self.error_code = error_code


class MissingError(StorageError):
    """The requested entry does not exist."""

    def __init__(self, detail: str = "") -> None:
        super().__init__("STORAGE_INTEGRITY_FAILED", detail or "missing")


class LimitExceeded(StorageError):
    """A file exceeds the size limit for its purpose."""

    def __init__(self, detail: str = "") -> None:
        super().__init__("STORAGE_INTEGRITY_FAILED", detail or "size limit exceeded")


def storage_error_code(exc: OSError) -> str:
    if exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1), errno.EFBIG):
        return "STORAGE_FULL"
    if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ELOOP, errno.ENOTDIR):
        return "PERMISSION_DENIED"
    return "STORAGE_INTEGRITY_FAILED"


def _oserror(exc: OSError, detail: str = "") -> StorageError:
    if isinstance(exc, FileNotFoundError):
        return MissingError(detail)
    return StorageError(storage_error_code(exc), detail)


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


def _fsync_classified(fd: int) -> None:
    try:
        fsync_fd(fd)
    except OSError as exc:
        raise _oserror(exc, "fsync") from exc


def _checked_dir(fd: int) -> int:
    """Take ownership of ``fd``; return it only if it is a directory, else close it."""
    try:
        is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
    except OSError as exc:
        os.close(fd)
        raise _oserror(exc, "fstat") from exc
    except BaseException:
        os.close(fd)
        raise
    if not is_dir:
        os.close(fd)
        raise StorageError("PERMISSION_DENIED", "not a directory")
    return fd


def _open_dir_chain(path: Path) -> tuple[int, frozenset[tuple[int, int]]]:
    """Open absolute ``path`` from ``/`` without following any symlink.

    Returns the directory fd and the (st_dev, st_ino) of every directory on the
    walked chain (``/`` .. ``path``). Any symlink or non-directory on the way
    (e.g. an ancestor swapped after canonicalisation) fails with PERMISSION_DENIED.
    """
    if not path.is_absolute():
        raise StorageError("PERMISSION_DENIED", "data root must be absolute")
    chain: set[tuple[int, int]] = set()
    try:
        fd = _checked_dir(os.open("/", _DIR_FLAGS))
    except OSError as exc:
        raise _oserror(exc, "root") from exc
    try:
        for part in path.parts[1:]:
            st = os.fstat(fd)
            chain.add((st.st_dev, st.st_ino))
            try:
                child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError as exc:
                raise StorageError("STORAGE_INTEGRITY_FAILED", "data root missing") from exc
            except OSError as exc:
                raise _oserror(exc, "data root path") from exc
            child = _checked_dir(child)
            os.close(fd)
            fd = child
        st = os.fstat(fd)
        chain.add((st.st_dev, st.st_ino))
    except OSError as exc:
        os.close(fd)
        raise _oserror(exc, "data root") from exc
    except BaseException:
        os.close(fd)
        raise
    return fd, frozenset(chain)


def _chain_within(
    canonical: Path, chain: frozenset[tuple[int, int]], protected_roots: tuple[Path, ...]
) -> bool:
    """Is a pinned directory (canonical path + walked identity chain) inside a protected root?

    Identity catches aliases that realpath() keeps distinct (e.g. macOS firmlinks
    under /System/Volumes/Data); the lexical test covers roots that do not exist.
    """
    for root in protected_roots:
        root_canonical = Path(os.path.realpath(root))
        if canonical == root_canonical or canonical.is_relative_to(root_canonical):
            return True
        try:
            st = os.stat(root_canonical)
        except OSError:
            continue
        if (st.st_dev, st.st_ino) in chain:
            return True
    return False


def _platform_supported() -> bool:
    needed_dir_fd = (os.open, os.mkdir, os.link, os.unlink, os.rmdir, os.stat)
    return (
        all(fn in os.supports_dir_fd for fn in needed_dir_fd)
        and os.link in os.supports_follow_symlinks
        and os.stat in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
        and all(hasattr(os, f) for f in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC"))
    )


class Loc(tuple):
    """Path components relative to one API directory, e.g. ("work", "locks", "x")."""

    __slots__ = ()

    @property
    def name(self) -> str:
        return self[-1]

    @property
    def parent(self) -> Loc:
        return Loc(self[:-1])

    def __truediv__(self, part: str) -> Loc:
        return Loc((*self, part))

    def __str__(self) -> str:
        return "/" + "/".join(self)


class NewFile:
    """Write handle for a newly created file; keeps its parent directory fd."""

    def __init__(self, fd: int, parent_fd: int) -> None:
        # Takes ownership of both fds, also when construction fails.
        try:
            self._file = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            os.close(parent_fd)
            raise
        self._parent_fd: int | None = parent_fd

    def write(self, data: bytes) -> int:
        return self._file.write(data)

    def flush(self) -> None:
        self._file.flush()

    def fileno(self) -> int:
        return self._file.fileno()

    def sync_parent(self) -> None:
        if self._parent_fd is not None:
            fsync_fd(self._parent_fd)

    def close(self) -> None:
        try:
            self._file.close()
        finally:
            if self._parent_fd is not None:
                os.close(self._parent_fd)
                self._parent_fd = None

    def __enter__(self) -> NewFile:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class ApiDataArea:
    """Confined, symlink-safe, durable file operations inside ``<data_root>/<api_id>``."""

    def __init__(self, data_root: Path, api_id: str) -> None:
        if not isinstance(api_id, str) or not _PART_RE.match(api_id):
            raise ValueError("invalid api_id")
        # Canonicalised exactly once; never re-resolved afterwards.
        self.data_root = Path(os.path.realpath(data_root))
        self.api_id = api_id
        self.root = self.data_root / api_id  # informational; never used for I/O
        self._root_fd: int | None = None
        self._root_chain: frozenset[tuple[int, int]] = frozenset()

    # -- lifecycle -------------------------------------------------------
    def _rootfd(self) -> int:
        """Pin the data root (see module doc) on first use and return its fd."""
        if self._root_fd is None:
            if not _platform_supported():
                raise StorageError("PERMISSION_DENIED", "platform lacks safe dir_fd ops")
            fd, chain = _open_dir_chain(self.data_root)
            self._root_fd = fd
            self._root_chain = chain
        return self._root_fd

    def pin(self) -> None:
        """Pin the data root now (before any check or I/O)."""
        self._rootfd()

    def root_within(self, protected_roots: tuple[Path, ...]) -> bool:
        """True if the pinned root is, or is inside, any protected root.

        Decided on the identities recorded while pinning (so a later swap of
        the pathname cannot change the answer), plus a lexical check on the
        canonical path for protected roots that do not exist (e.g. /data).
        """
        self._rootfd()
        return _chain_within(self.data_root, self._root_chain, protected_roots)

    def close(self) -> None:
        if self._root_fd is not None:
            fd, self._root_fd = self._root_fd, None
            os.close(fd)

    def __enter__(self) -> ApiDataArea:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    # -- locations ---------------------------------------------------------
    def path(self, *parts: str) -> Loc:
        """Build a validated writable location."""
        loc = Loc(parts)
        self._check(loc, WRITABLE_AREAS)
        return loc

    @staticmethod
    def _check(loc: object, areas: frozenset[tuple[str, str]]) -> Loc:
        if not isinstance(loc, Loc):
            raise StorageError("PERMISSION_DENIED", "location must be a Loc")
        if len(loc) < 2 or (loc[0], loc[1]) not in areas:
            raise StorageError("PERMISSION_DENIED", "area not permitted")
        for part in loc:
            if not isinstance(part, str) or not _PART_RE.match(part) or part in (".", ".."):
                raise StorageError("PERMISSION_DENIED", "invalid path component")
        return loc

    @staticmethod
    def relative(loc: Loc, area: str) -> str:
        """Internal reference relative to ``<api>/<area>`` (e.g. records)."""
        if not loc or loc[0] != area:
            raise StorageError("PERMISSION_DENIED", "wrong area")
        return "/".join(loc[1:])

    # -- traversal -----------------------------------------------------------
    @staticmethod
    def _opendir(parent_fd: int, name: str) -> int:
        try:
            fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except OSError as exc:
            raise _oserror(exc, "directory") from exc
        return _checked_dir(fd)

    def _child_dir(self, parent_fd: int, name: str, create: bool) -> int:
        try:
            return self._opendir(parent_fd, name)
        except MissingError:
            if not create:
                raise
        try:
            os.mkdir(name, 0o750, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _oserror(exc, "mkdir") from exc
        _fsync_classified(parent_fd)
        return self._opendir(parent_fd, name)

    def _walk(self, parts: tuple[str, ...], create: bool) -> int:
        """Return an fd for ``<api>/<parts...>``; caller closes it."""
        fd = self._child_dir(self._rootfd(), self.api_id, create)
        try:
            for part in parts:
                child = self._child_dir(fd, part, create)
                os.close(fd)
                fd = child
        except BaseException:
            os.close(fd)
            raise
        return fd

    # -- directories ---------------------------------------------------------
    def ensure_dir(self, loc: Loc) -> None:
        self._check(loc, WRITABLE_AREAS)
        os.close(self._walk(tuple(loc), create=True))

    def dir_exists(self, loc: Loc) -> bool:
        self._check(loc, READABLE_AREAS)
        try:
            os.close(self._walk(tuple(loc), create=False))
        except MissingError:
            return False
        return True

    def list_dir(self, loc: Loc) -> list[str]:
        """Entry names of a directory; [] if it does not exist."""
        self._check(loc, READABLE_AREAS)
        try:
            fd = self._walk(tuple(loc), create=False)
        except MissingError:
            return []
        try:
            return sorted(os.listdir(fd))
        finally:
            os.close(fd)

    def entry_exists(self, loc: Loc) -> bool:
        self._check(loc, READABLE_AREAS)
        try:
            pfd = self._walk(tuple(loc.parent), create=False)
        except MissingError:
            return False
        try:
            os.stat(loc.name, dir_fd=pfd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise _oserror(exc) from exc
        finally:
            os.close(pfd)

    def same_filesystem(self, *locs: Loc) -> bool:
        devices = set()
        for loc in locs:
            self._check(loc, WRITABLE_AREAS)
            fd = self._walk(tuple(loc), create=False)
            try:
                devices.add(os.fstat(fd).st_dev)
            except OSError as exc:
                raise _oserror(exc) from exc
            finally:
                os.close(fd)
        return len(devices) == 1

    def remove_empty_dir(self, loc: Loc) -> None:
        self._check(loc, WRITABLE_AREAS)
        pfd = self._walk(tuple(loc.parent), create=False)
        try:
            try:
                os.rmdir(loc.name, dir_fd=pfd)
            except OSError:
                return  # not empty or already gone: leave it
            _fsync_classified(pfd)
        finally:
            os.close(pfd)

    # -- writing ---------------------------------------------------------------
    def open_exclusive(self, loc: Loc) -> NewFile:
        """Create a new file for writing; fails if any entry with that name exists."""
        self._check(loc, WRITABLE_AREAS)
        pfd = self._walk(tuple(loc.parent), create=True)
        try:
            fd = os.open(loc.name, _NEW_FLAGS, 0o640, dir_fd=pfd)
        except FileExistsError as exc:
            os.close(pfd)
            raise StorageError("STORAGE_INTEGRITY_FAILED", "file exists") from exc
        except OSError as exc:
            os.close(pfd)
            raise _oserror(exc) from exc
        return NewFile(fd, pfd)

    def finish_file(self, handle: NewFile) -> None:
        """Flush and fsync a new file and its directory entry, then close it."""
        try:
            handle.flush()
            fsync_fd(handle.fileno())
            handle.sync_parent()
        except OSError as exc:
            raise _oserror(exc) from exc
        finally:
            handle.close()

    def write_new(self, loc: Loc, data: bytes) -> None:
        """Durably create ``loc`` with ``data``; never overwrites an existing entry."""
        self._check(loc, WRITABLE_AREAS)
        pfd = self._walk(tuple(loc.parent), create=True)
        tmp = f".{loc.name}.tmp-{uuid.uuid4().hex}"
        try:
            try:
                os.stat(loc.name, dir_fd=pfd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise _oserror(exc) from exc
            else:
                raise StorageError("STORAGE_INTEGRITY_FAILED", "file exists")
            try:
                fd = os.open(tmp, _NEW_FLAGS, 0o640, dir_fd=pfd)
            except OSError as exc:
                raise _oserror(exc) from exc
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                fsync_fd(fd)
            except OSError as exc:
                raise _oserror(exc) from exc
            finally:
                os.close(fd)
            self._link_unlink(pfd, tmp, pfd, loc.name)
        finally:
            try:
                os.unlink(tmp, dir_fd=pfd)
            except OSError:
                pass
            os.close(pfd)

    def link_no_clobber(self, src: Loc, dst: Loc) -> None:
        """Give the single-link regular file ``src`` the new name ``dst`` (same FS)."""
        self._check(src, WRITABLE_AREAS)
        self._check(dst, WRITABLE_AREAS)
        spfd = self._walk(tuple(src.parent), create=False)
        try:
            dpfd = self._walk(tuple(dst.parent), create=True)
            try:
                try:
                    st = os.stat(src.name, dir_fd=spfd, follow_symlinks=False)
                except OSError as exc:
                    raise _oserror(exc) from exc
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                    raise StorageError("STORAGE_INTEGRITY_FAILED", "source not a single-link file")
                self._link_unlink(spfd, src.name, dpfd, dst.name)
            finally:
                os.close(dpfd)
        finally:
            os.close(spfd)

    @staticmethod
    def _link_unlink(spfd: int, sname: str, dpfd: int, dname: str) -> None:
        try:
            os.link(sname, dname, src_dir_fd=spfd, dst_dir_fd=dpfd, follow_symlinks=False)
        except FileExistsError as exc:
            raise StorageError("STORAGE_INTEGRITY_FAILED", "target exists") from exc
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise StorageError("STORAGE_INTEGRITY_FAILED", "cross-device") from exc
            raise _oserror(exc) from exc
        try:
            fsync_fd(dpfd)
            os.unlink(sname, dir_fd=spfd)
            fsync_fd(spfd)
        except OSError as exc:
            raise _oserror(exc) from exc

    # -- reading ---------------------------------------------------------------
    @contextmanager
    def _open_committed(self, loc: Loc, max_bytes: int) -> Iterator[tuple[int, int]]:
        """Open a regular, single-link, self-owned file no larger than ``max_bytes``."""
        self._check(loc, READABLE_AREAS)
        pfd = self._walk(tuple(loc.parent), create=False)
        try:
            try:
                fd = os.open(loc.name, _READ_FLAGS, dir_fd=pfd)
            except OSError as exc:
                raise _oserror(exc) from exc
        finally:
            os.close(pfd)
        try:
            try:
                st = os.fstat(fd)
            except OSError as exc:
                raise _oserror(exc) from exc
            if not stat.S_ISREG(st.st_mode):
                raise StorageError("STORAGE_INTEGRITY_FAILED", "not a regular file")
            if st.st_nlink != 1:
                raise StorageError("STORAGE_INTEGRITY_FAILED", "unexpected hardlink alias")
            if st.st_uid != os.geteuid():
                raise StorageError("STORAGE_INTEGRITY_FAILED", "unexpected owner")
            if st.st_size > max_bytes:
                raise LimitExceeded()
            yield fd, st.st_size
        finally:
            os.close(fd)

    def read_bytes(self, loc: Loc, max_bytes: int) -> bytes:
        with self._open_committed(loc, max_bytes) as (fd, _):
            chunks: list[bytes] = []
            total = 0
            while True:
                try:
                    chunk = os.read(fd, _CHUNK)
                except OSError as exc:
                    raise _oserror(exc) from exc
                if not chunk:
                    return b"".join(chunks)
                total += len(chunk)
                if total > max_bytes:
                    raise LimitExceeded()
                chunks.append(chunk)

    def hash_file(self, loc: Loc, max_bytes: int) -> tuple[str, int]:
        """Stream SHA-256 and size of a committed file, bounded by ``max_bytes``."""
        with self._open_committed(loc, max_bytes) as (fd, _):
            digest = hashlib.sha256()
            total = 0
            while True:
                try:
                    chunk = os.read(fd, _CHUNK)
                except OSError as exc:
                    raise _oserror(exc) from exc
                if not chunk:
                    return digest.hexdigest(), total
                total += len(chunk)
                if total > max_bytes:
                    raise LimitExceeded()
                digest.update(chunk)

    # -- locking ---------------------------------------------------------------
    @contextmanager
    def exclusive_lock(self, loc: Loc, *, blocking: bool = False) -> Iterator[None]:
        """Exclusive flock bound to this process's lifetime.

        Non-blocking by default: raises ``StorageError("TARGET_BUSY")`` if
        another holder exists. ``blocking=True`` waits (only for short critical
        sections). The kernel releases the lock if the process dies; PIDs are
        never used to steal a lock. Single-host only.
        """
        self._check(loc, WRITABLE_AREAS)
        pfd = self._walk(tuple(loc.parent), create=True)
        try:
            fd = os.open(loc.name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o640, dir_fd=pfd)
        except OSError as exc:
            raise _oserror(exc) from exc
        finally:
            os.close(pfd)
        try:
            try:
                mode = os.fstat(fd).st_mode
            except OSError as exc:
                raise _oserror(exc) from exc
            if not stat.S_ISREG(mode):
                raise StorageError("PERMISSION_DENIED", "lock is not a regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StorageError("TARGET_BUSY") from exc
            except OSError as exc:
                raise _oserror(exc) from exc
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # -- fixture data root -------------------------------------------------------
    def has_fixture_marker(self) -> bool:
        """True if the data root carries the explicit fixture-root marker file."""
        root = self._rootfd()
        try:
            fd = os.open(FIXTURE_ROOT_MARKER, _READ_FLAGS, dir_fd=root)
        except OSError:
            return False
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid():
                return False
            return os.read(fd, len(FIXTURE_ROOT_MARKER_CONTENT) + 1) == FIXTURE_ROOT_MARKER_CONTENT
        except OSError:
            return False
        finally:
            os.close(fd)


def is_within(path: Path, root: Path) -> bool:
    resolved = Path(path).resolve()
    base = Path(root).resolve()
    return resolved == base or resolved.is_relative_to(base)


def init_fixture_data_root(data_root: Path, protected_roots: tuple[Path, ...] = ()) -> None:
    """Mark an existing, empty directory as a disposable fixture data root.

    Refuses production locations (``/data``) and anything inside
    ``protected_roots`` (decided on the pinned directory, by identity as well).
    Never touches a non-empty directory. The marker records intent only; it is
    not an authentication credential.
    """
    root = Path(data_root)
    if root.is_symlink() or not root.is_dir():
        raise StorageError("PERMISSION_DENIED", "fixture root must be an existing directory")
    canonical = Path(os.path.realpath(root))
    fd, chain = _open_dir_chain(canonical)
    try:
        if _chain_within(canonical, chain, (PRODUCTION_DATA_ROOT, *protected_roots)):
            raise StorageError("PERMISSION_DENIED", "protected location")
        if os.listdir(fd):
            raise StorageError("PERMISSION_DENIED", "fixture root must be empty")
        mfd = os.open(FIXTURE_ROOT_MARKER, _NEW_FLAGS, 0o640, dir_fd=fd)
        try:
            os.write(mfd, FIXTURE_ROOT_MARKER_CONTENT)
            fsync_fd(mfd)
        finally:
            os.close(mfd)
        fsync_fd(fd)
    finally:
        os.close(fd)
