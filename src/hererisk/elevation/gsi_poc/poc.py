"""Phase 1-D.1: plan / fetch one GSI DEM10B PNG tile into a dedicated PoC directory.

``plan_fetch(lat, lon, zoom)`` computes the tile with ``locate_pixel`` and the
URL from the production Source Definition entry ``gsi-dem10b-candidate``
(read only; its ``approval_ref`` stays null and is recorded as such). The URL
must be ``https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png``.

``run_fetch_poc(plan, output_dir, allow_network=...)``:
  * without ``allow_network``: returns the plan only; no network, no writes
  * with it: at most one HTTPS GET (``http_fetch``), streamed into a temporary
    file in the PoC directory; size / SHA-256 re-read check, ``check_png``,
    ``normalize_tile`` (container check + strict decode) and Validate statistics; then the PNG is linked to its
    final name (no clobber) and an evidence JSON is written (no clobber).
    A failure removes only this run's temporary file; nothing else is
    modified or deleted.

The PoC directory must be an explicit, dedicated directory: an existing real
directory (not a symlink) outside /data, the repository and any fixture data
root, either empty (it is then marked) or already carrying the PoC marker.
Saved files are PoC evidence only: not fixture- or production-approved, not
for publication or redistribution, and must not be fed into the pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from hererisk.common.config import ConfigurationManager
from hererisk.common.result import PipelineError
from hererisk.common.storage import (
    FIXTURE_ROOT_MARKER,
    PRODUCTION_DATA_ROOT,
    StorageError,
    _chain_within,
    _open_dir_chain,
    fsync_fd,
)
from hererisk.elevation.gsi_poc import http_fetch
from hererisk.elevation.lookup.core import locate_pixel
from hererisk.elevation.normalize.convert import normalize_tile
from hererisk.elevation.validate.core import validate_candidate

SOURCE_REF = "gsi-dem10b-candidate"
EVIDENCE_SCHEMA = "hererisk-gsi-poc-evidence-v0.1"
POC_MARKER = ".hererisk-gsi-poc-dir"
POC_MARKER_CONTENT = b"hererisk gsi dem10b acquisition poc v1\n"
_TEMPLATE_RE = re.compile(r"^https://cyberjapandata\.gsi\.go\.jp/xyz/dem_png/\{z\}/\{x\}/\{y\}\.png$")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_NEW_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class FetchPlan:
    z: int
    x: int
    y: int
    url: str
    host: str
    path: str
    source: dict[str, Any]

    @property
    def basename(self) -> str:
        return f"dem_png_{self.z}_{self.x}_{self.y}"


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan_fetch(latitude: float, longitude: float, zoom: int, *, repo_root: Path) -> FetchPlan:
    """Tile + URL for (lat, lon) at ``zoom``; zoom must equal the source's (Z14)."""
    snapshot = ConfigurationManager(repo_root, repo_root).load("api", "elevation", "sources")
    source = snapshot.data["sources"][SOURCE_REF]
    acquisition = source["acquisition"]
    template = acquisition["url_template"]
    if not _TEMPLATE_RE.match(template):
        raise PipelineError("INVALID_CONFIGURATION", "unexpected GSI URL template")
    if type(zoom) is not int or zoom != acquisition["zoom"]:
        raise PipelineError("INVALID_INPUT", "zoom must equal the DEM10B source zoom")
    location = locate_pixel(latitude, longitude, zoom)
    url = (template.replace("{z}", str(location.z)).replace("{x}", str(location.tile_x))
           .replace("{y}", str(location.tile_y)))
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != http_fetch.ALLOWED_HOST or parts.port \
            or parts.query or parts.fragment or parts.username:
        raise PipelineError("INVALID_CONFIGURATION", "URL not allowed")
    return FetchPlan(
        z=location.z, x=location.tile_x, y=location.tile_y, url=url,
        host=parts.hostname, path=parts.path,
        source={
            "source_ref": SOURCE_REF,
            "definition_revision": snapshot.data["definition_revision"],
            "raw_sha256": snapshot.raw_sha256,
            "approval_ref": source["approval_ref"],  # null: not approved for acquisition
            "provider": dict(source["provider"]),
            "name": source["name"],
            "official_page_url": source["official_page_url"],
            "terms_url": source["usage"]["terms_url"],
            "vertical_reference": source["vertical_reference"],
        },
    )


# -- dedicated PoC directory ------------------------------------------------------------------
def _open_poc_dir(output_dir: Path, protected: tuple[Path, ...]) -> int:
    path = Path(output_dir)
    if path.is_symlink() or not path.is_dir():
        raise PipelineError("INVALID_INPUT", "output directory must be an existing directory")
    canonical = Path(os.path.realpath(path))
    try:
        fd, chain = _open_dir_chain(canonical)
    except StorageError as exc:
        raise PipelineError("INVALID_INPUT", "output directory not usable") from exc
    try:
        if _chain_within(canonical, chain, (PRODUCTION_DATA_ROOT, *protected)):
            raise PipelineError("INVALID_INPUT", "output directory in a protected location")
        names = set(os.listdir(fd))
        if FIXTURE_ROOT_MARKER in names:
            raise PipelineError("INVALID_INPUT", "output directory is a fixture data root")
        if POC_MARKER in names:
            mfd = os.open(POC_MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            try:
                st = os.fstat(mfd)
                ok = stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and \
                    os.read(mfd, 128) == POC_MARKER_CONTENT
            finally:
                os.close(mfd)
            if not ok:
                raise PipelineError("INVALID_INPUT", "invalid PoC marker")
        elif names:
            raise PipelineError("INVALID_INPUT", "output directory must be empty or a PoC directory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _mark(fd: int) -> None:
    try:
        mfd = os.open(POC_MARKER, _NEW_FLAGS, 0o640, dir_fd=fd)
    except FileExistsError:
        return
    try:
        os.write(mfd, POC_MARKER_CONTENT)
        fsync_fd(mfd)
    finally:
        os.close(mfd)
    fsync_fd(fd)


def _exists(fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _write_new(fd: int, name: str, data: bytes) -> None:
    tmp = f".{name}.tmp-{uuid.uuid4().hex}"
    tfd = os.open(tmp, _NEW_FLAGS, 0o640, dir_fd=fd)
    try:
        try:
            os.write(tfd, data)
            fsync_fd(tfd)
        finally:
            os.close(tfd)
        os.link(tmp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        fsync_fd(fd)
    finally:
        try:
            os.unlink(tmp, dir_fd=fd)
        except OSError:
            pass
        fsync_fd(fd)


# -- run --------------------------------------------------------------------------------------
def plan_document(plan: FetchPlan) -> dict[str, Any]:
    return {
        "url": plan.url,
        "tile": {"z": plan.z, "x": plan.x, "y": plan.y},
        "files": {"png": f"{plan.basename}.png", "evidence": f"{plan.basename}.json"},
        "max_tiles": 1,
        "network": "not used (pass --allow-network to fetch this single tile)",
    }


def run_fetch_poc(
    plan: FetchPlan,
    output_dir: Path,
    *,
    allow_network: bool,
    protected_roots: tuple[Path, ...],
    connection_factory: Callable[[str], http_fetch.Connection] = http_fetch.default_connection_factory,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Plan (no network) or fetch exactly one tile. Returns the evidence document."""
    if allow_network is not True:
        return {"mode": "plan", "network_used": False, **plan_document(plan), "evidence": None}

    png_name, evidence_name = f"{plan.basename}.png", f"{plan.basename}.json"
    fd = _open_poc_dir(output_dir, protected_roots)
    try:
        if _exists(fd, png_name) or _exists(fd, evidence_name):
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "tile already fetched (no overwrite)")
        _mark(fd)
        tmp = f".{png_name}.part-{uuid.uuid4().hex}"
        try:
            tfd = os.open(tmp, _NEW_FLAGS, 0o640, dir_fd=fd)
            digest = hashlib.sha256()
            requested_at = _utc(clock())
            try:
                def sink(chunk: bytes) -> None:
                    digest.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        view = view[os.write(tfd, view):]

                response = http_fetch.fetch_png(plan.host, plan.path, sink,
                                                connection_factory=connection_factory)
                fsync_fd(tfd)
            finally:
                os.close(tfd)
            acquired_at = _utc(clock())
            sha256 = digest.hexdigest()
            rfd = os.open(tmp, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            try:
                parts: list[bytes] = []
                total = 0
                while total <= http_fetch.MAX_BODY_BYTES:
                    piece = os.read(rfd, http_fetch.CHUNK)
                    if not piece:
                        break
                    parts.append(piece)
                    total += len(piece)
                stored = b"".join(parts)
            finally:
                os.close(rfd)
            if len(stored) != response.size_bytes or hashlib.sha256(stored).hexdigest() != sha256:
                raise PipelineError("STORAGE_INTEGRITY_FAILED", "re-read mismatch")
            # normalize_tile runs the Download container check (check_png) first,
            # then the bounded strict decode; Validate computes the statistics.
            candidate = normalize_tile(stored, {"z": plan.z, "x": plan.x, "y": plan.y},
                                       max_png_bytes=http_fetch.MAX_BODY_BYTES)
            stats = validate_candidate(candidate, expected_tile={"z": plan.z, "x": plan.x, "y": plan.y})
            del candidate
            try:
                os.link(tmp, png_name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError as exc:
                raise PipelineError("STORAGE_INTEGRITY_FAILED", "target exists") from exc
            fsync_fd(fd)
        finally:
            try:
                os.unlink(tmp, dir_fd=fd)  # only this run's temporary name
            except OSError:
                pass
            fsync_fd(fd)

        evidence = {
            "schema": EVIDENCE_SCHEMA,
            "poc_only": True,
            "notice": ("Phase 1-D.1 PoC evidence. Not fixture- or production-approved, "
                       "not for publication or redistribution, not pipeline input."),
            "dataset": "DEM10B",
            "layer": "dem_png",
            "url": plan.url,
            "tile": {"z": plan.z, "x": plan.x, "y": plan.y},
            "requested_at": requested_at,
            "acquired_at": acquired_at,
            "http_status": response.http_status,
            "content_type": response.content_type,
            "content_length": response.content_length,
            "size_bytes": response.size_bytes,
            "sha256": sha256,
            "png_file": png_name,
            "checks": {"png_container": "passed", "decode": "passed", "profile": "passed"},
            "statistics": {**stats.stats(), "warning": stats.warning},
            "source_definition": plan.source,
            "attribution": "出典：国土地理院（標高タイル DEM10B）",
            "unconfirmed": ["vertical_reference", "survey_period", "revision_status",
                            "redistribution_terms"],
        }
        _write_new(fd, evidence_name,
                   (json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
        return {"mode": "fetch", "network_used": True, **plan_document(plan),
                "network": "used: 1 request", "evidence": evidence}
    except OSError as exc:
        raise PipelineError("STORAGE_INTEGRITY_FAILED", "PoC directory I/O failed") from exc
    finally:
        os.close(fd)
