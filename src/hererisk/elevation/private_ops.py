"""OWNER helpers for the private_experiment workflow (Phase 1-H).

These commands only remove repetitive manual work (directory layout, JSON
editing, SHA-256 digests, file permissions, audit lines). They never decide
anything on the OWNER's behalf:

* no approval exists until the OWNER runs ``approval-register`` with their own
  approver / basis / validity values and repeats the approval id in
  ``--confirm``; nothing in the pipeline or the API calls these helpers;
* a ``publish`` approval can only be registered after a Validate SUCCESS of
  the same approval (``--reviewed-run-id``), so acquisition and publication
  stay two explicit OWNER steps;
* everything is written under one "private base" directory outside the
  repository (secrets, real data, approvals never enter Git).

Layout of a private base::

    <base>/                     0700
      data/                     private_experiment data root (init-private-root)
      approvals/                approval store (revocations.json, approvals/*.json)
      config/api/elevation/conf/sources.json   private Source Definition
      secrets/api-token         Bearer token (0600), secrets/auth-header (curl -H @file)
      audit/approvals.log       append-only audit lines (no secrets)
"""

from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from hererisk.common.api_auth import read_token_file, write_new_token_file
from hererisk.common.approval_store import (
    APPROVAL_RECORD_SCHEMA,
    RECORD_SCHEMA_ID,
    REVOCATIONS_SCHEMA,
    REVOCATIONS_SCHEMA_ID,
    record_digest,
)
from hererisk.common.config import (
    ConfigurationError,
    ConfigurationManager,
    parse_strict_json,
    thaw,
    validate_with_schema,
)
from hererisk.common.storage import init_private_data_root, is_within

API_ID = "elevation"
SOURCE_REF = "gsi-dem10b-candidate"
PIPELINE = {"id": "elevation-download", "version": "0.1"}
MAX_VALID_DAYS = 30
_PRIVATE_ID_RE = re.compile(r"^apr-private-[a-z0-9][a-z0-9-]{2,50}$")


class PrivateOpsError(Exception):
    """Refused. Messages are fixed texts (no secrets, no coordinates)."""


@dataclass(frozen=True)
class PrivateBase:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def approvals(self) -> Path:
        return self.root / "approvals"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def sources(self) -> Path:
        return self.config / "api" / API_ID / "conf" / "sources.json"

    @property
    def token(self) -> Path:
        return self.root / "secrets" / "api-token"

    @property
    def auth_header(self) -> Path:
        return self.root / "secrets" / "auth-header"

    @property
    def audit(self) -> Path:
        return self.root / "audit" / "approvals.log"

    def record(self, approval_id: str) -> Path:
        return self.approvals / "approvals" / f"{approval_id}.json"


def private_base(path: Path, repo_root: Path) -> PrivateBase:
    root = Path(path)
    if not root.is_absolute():
        raise PrivateOpsError("private base must be an absolute path")
    if os.path.realpath(root) != str(root):
        raise PrivateOpsError("private base path must not contain symlinks")
    if is_within(root, repo_root):
        raise PrivateOpsError("private base must be outside the repository")
    return PrivateBase(root)


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_new(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{_secrets.token_hex(8)}")
    _write_new(tmp, data)
    os.replace(tmp, path)


def _json_bytes(doc: Any) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _audit(base: PrivateBase, line: str, clock: Callable[[], datetime]) -> None:
    fd = os.open(base.audit, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    try:
        os.write(fd, f"{_utc(clock())} {line}\n".encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- 1. layout ------------------------------------------------------------------------------
def init_base(base: PrivateBase, repo_root: Path, clock: Callable[[], datetime] = _now) -> None:
    """Create the whole layout once (refuses a non-empty base). Never prints the token."""
    root = base.root
    if root.exists():
        if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
            raise PrivateOpsError("private base must be absent or an empty directory")
    else:
        root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    for sub in ("data", "approvals", "approvals/approvals", "config", "secrets", "audit"):
        (root / sub).mkdir(mode=0o700, exist_ok=True)
    init_private_data_root(base.data, protected_roots=(repo_root,))
    _write_new(base.approvals / "revocations.json",
               _json_bytes({"schema": REVOCATIONS_SCHEMA_ID, "revoked": []}))
    write_new_token_file(base.token)
    token = read_token_file(base.token)[-1]
    _write_new(base.auth_header, f"Authorization: Bearer {token}\n".encode("ascii"))
    _audit(base, "init private base", clock)


# -- 2. private Source Definition ---------------------------------------------------------------
def write_definition(base: PrivateBase, repo_root: Path, *, approval_id: str,
                     tiles: list[tuple[int, int]], attribution_text: str,
                     vertical_reference: str, review_ref: str, revision: str,
                     replace: bool = False, clock: Callable[[], datetime] = _now) -> str:
    """Derive the private Source Definition from the committed one; return its SHA-256.

    Only the ``gsi-dem10b-candidate`` entry and ``definition_revision`` change.
    Changing it later invalidates every approval bound to the previous bytes.
    """
    if not _PRIVATE_ID_RE.match(approval_id):
        raise PrivateOpsError("approval id must start with apr-private-")
    if not tiles or len(set(tiles)) != len(tiles):
        raise PrivateOpsError("give each tile once")
    for text in (attribution_text, vertical_reference, review_ref, revision):
        if not text.strip() or "<" in text:
            raise PrivateOpsError("all values must be real (no placeholders)")
    if base.sources.exists() and not replace:
        raise PrivateOpsError("private definition exists (use --replace)")
    doc = json.loads((repo_root / "api" / API_ID / "conf" / "sources.json").read_text("utf-8"))
    src = doc["sources"][SOURCE_REF]
    src["acquisition"]["tiles"] = [{"x": x, "y": y} for x, y in tiles]
    src["vertical_reference"] = vertical_reference
    src["usage"]["attribution_text"] = attribution_text
    src["usage"]["review_ref"] = review_ref
    src["pipeline"] = dict(PIPELINE)
    src["approval_ref"] = approval_id
    doc["definition_revision"] = revision
    base.sources.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = _json_bytes(doc)
    if replace and base.sources.exists():
        _replace(base.sources, data)
    else:
        _write_new(base.sources, data)
    try:
        snapshot = load_definition(base, repo_root)
    except ConfigurationError as exc:
        raise PrivateOpsError("private definition does not validate") from exc
    _audit(base, f"definition revision={revision} sha256={snapshot.raw_sha256} "
                 f"approval_ref={approval_id}", clock)
    return snapshot.raw_sha256


def load_definition(base: PrivateBase, repo_root: Path):
    return ConfigurationManager(base.config, repo_root).load("api", API_ID, "sources")


# -- 3. approval registration (an explicit OWNER act) ------------------------------------------
def register_approval(base: PrivateBase, repo_root: Path, *, approval_id: str, confirm: str,
                      operations: list[str], regions: list[str], approved_by: str,
                      basis_ref: str,
                      valid_days: int, replace: bool = False,
                      license_text: str | None = None, attribution_url: str | None = None,
                      usage_review_ref: str | None = None, reviewed_run_id: str | None = None,
                      clock: Callable[[], datetime] = _now) -> dict[str, Any]:
    if confirm != approval_id:
        raise PrivateOpsError("--confirm must repeat the approval id")
    if not _PRIVATE_ID_RE.match(approval_id):
        raise PrivateOpsError("approval id must start with apr-private-")
    for text in (approved_by, basis_ref):
        if not text.strip() or "<" in text or "test-only" in text:
            raise PrivateOpsError("approver and basis must be real values")
    if not 1 <= valid_days <= MAX_VALID_DAYS:
        raise PrivateOpsError(f"validity must be 1-{MAX_VALID_DAYS} days")
    definition = load_definition(base, repo_root)
    source = definition.data["sources"][SOURCE_REF]
    prefectures = definition.data["prefectures"]
    if not regions or len(set(regions)) != len(regions) or any(
            r not in prefectures or not prefectures[r]["targeted"]
            or SOURCE_REF not in prefectures[r]["source_refs"] for r in regions):
        raise PrivateOpsError("regions must be targeted for the source in the definition")
    if source["approval_ref"] != approval_id:
        raise PrivateOpsError("the private definition names another approval id")
    acquisition = source["acquisition"]
    host = urlsplit(acquisition["url_template"]).hostname
    now = clock().replace(microsecond=0)
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA_ID,
        "approval_id": approval_id,
        "execution_context": "private_experiment",
        "api_id": API_ID,
        "source_ref": SOURCE_REF,
        "operations": list(operations),
        "region_codes": sorted(regions),
        "tiles": [{"z": acquisition["zoom"], "x": t["x"], "y": t["y"]}
                  for t in acquisition["tiles"]],
        "definition": {"revision": definition.data["definition_revision"],
                       "raw_sha256": definition.raw_sha256},
        "valid_from": _utc(now),
        "expires_at": _utc(now + timedelta(days=valid_days)),
        "approved_by": approved_by,
        "approval_basis_ref": basis_ref,
    }
    if "download" in operations:
        record["acquisition"] = {"allowed_host": host, "max_tiles_per_run": len(acquisition["tiles"]),
                                 "max_tile_bytes": 1048576, "max_pending_acquisitions": 1}
    if "publish" in operations:
        for value in (license_text, attribution_url, usage_review_ref, reviewed_run_id):
            if not value or "<" in value:
                raise PrivateOpsError("publish needs licence, attribution URL, usage review "
                                      "and a reviewed Validate run")
        _check_reviewed_run(base, approval_id, reviewed_run_id)
        record["approval_basis_ref"] = f"{basis_ref}; reviewed_validate_run={reviewed_run_id}"
        record["publication"] = {
            "license": license_text, "attribution_url": attribution_url,
            "attribution_text": source["usage"]["attribution_text"],
            "private_use": {"purpose": "non_commercial_personal_experiment",
                            "access": "owner_only_loopback",
                            "usage_review_ref": usage_review_ref,
                            "confirmed_by": approved_by, "confirmed_at": _utc(now)}}
    elif any(v is not None for v in (license_text, attribution_url, usage_review_ref,
                                     reviewed_run_id)):
        raise PrivateOpsError("publication values are only for a publish approval")
    record["record_sha256"] = record_digest(record)
    try:
        validate_with_schema(record, APPROVAL_RECORD_SCHEMA)
    except ConfigurationError as exc:
        raise PrivateOpsError("record does not satisfy the approval schema") from exc
    path = base.record(approval_id)
    data = _json_bytes(record)
    if path.exists():
        if not replace:
            raise PrivateOpsError("record exists (use --replace to update it)")
        _replace(path, data)
    else:
        if replace:
            raise PrivateOpsError("no record to replace")
        _write_new(path, data)
    _audit(base, f"{'update' if replace else 'register'} {approval_id} "
                 f"sha256={record['record_sha256']} operations={','.join(operations)} "
                 f"expires_at={record['expires_at']} by={approved_by}", clock)
    return record


def _check_reviewed_run(base: PrivateBase, approval_id: str, run_id: str | None) -> None:
    if not run_id or not re.match(r"^[0-9a-f-]{36}$", run_id):
        raise PrivateOpsError("reviewed run id is not a run id")
    path = base.data / API_ID / "records" / "validations" / f"{run_id}.json"
    try:
        doc = parse_strict_json(path.read_bytes())
    except (OSError, ConfigurationError) as exc:
        raise PrivateOpsError("no Validate record for the reviewed run") from exc
    if doc.get("status") != "SUCCESS" or doc.get("execution_context") != "private_experiment" \
            or doc.get("authorization_ref") != approval_id:
        raise PrivateOpsError("the reviewed run is not a private Validate SUCCESS of this approval")


def revoke_approval(base: PrivateBase, *, approval_id: str, confirm: str, reason_ref: str,
                    clock: Callable[[], datetime] = _now) -> None:
    if confirm != approval_id:
        raise PrivateOpsError("--confirm must repeat the approval id")
    if not reason_ref.strip() or "<" in reason_ref:
        raise PrivateOpsError("give a real reason reference")
    path = base.approvals / "revocations.json"
    doc = parse_strict_json(path.read_bytes())
    validate_with_schema(doc, REVOCATIONS_SCHEMA)
    if any(r["approval_id"] == approval_id for r in doc["revoked"]):
        raise PrivateOpsError("already revoked")
    doc["revoked"].append({"approval_id": approval_id, "revoked_at": _utc(clock()),
                           "reason_ref": reason_ref})
    _replace(path, _json_bytes(doc))
    _audit(base, f"revoke {approval_id} reason={reason_ref}", clock)


# -- 4. status (read only; no secrets, no coordinates) ---------------------------------------------
def status(base: PrivateBase, repo_root: Path, clock: Callable[[], datetime] = _now) -> dict:
    now = _utc(clock())
    out: dict[str, Any] = {"definition": None, "approvals": [], "runs": [], "registry": None,
                           "token_file": base.token.is_file()}
    try:
        definition = load_definition(base, repo_root)
        src = definition.data["sources"][SOURCE_REF]
        out["definition"] = {"revision": definition.data["definition_revision"],
                             "raw_sha256": definition.raw_sha256,
                             "approval_ref": src["approval_ref"],
                             "tiles": thaw(src["acquisition"]["tiles"])}
    except (ConfigurationError, OSError, KeyError):
        out["definition"] = "invalid or missing"
    revoked: set[str] = set()
    try:
        revoked = {r["approval_id"] for r in
                   parse_strict_json((base.approvals / "revocations.json").read_bytes())["revoked"]}
    except (ConfigurationError, OSError, KeyError):
        out["revocations"] = "invalid or missing"
    for path in sorted((base.approvals / "approvals").glob("*.json")):
        try:
            rec = parse_strict_json(path.read_bytes())
            out["approvals"].append({
                "approval_id": rec.get("approval_id"), "operations": rec.get("operations"),
                "valid_from": rec.get("valid_from"), "expires_at": rec.get("expires_at"),
                "in_force": rec.get("valid_from", "~") <= now < rec.get("expires_at", ""),
                "revoked": rec.get("approval_id") in revoked,
                "digest_ok": record_digest(rec) == rec.get("record_sha256"),
                "matches_definition": isinstance(out["definition"], dict)
                and rec.get("definition", {}).get("raw_sha256") == out["definition"]["raw_sha256"],
            })
        except (ConfigurationError, OSError):
            out["approvals"].append({"file": path.name, "error": "unreadable"})
    records = base.data / API_ID / "records"
    for kind in ("normalizations", "validations", "publications"):
        for path in sorted((records / kind).glob("*.json")):
            try:
                rec = parse_strict_json(path.read_bytes())
                out["runs"].append({"stage": kind, "run_id": rec.get("run_id"),
                                    "status": rec.get("status"),
                                    "authorization_ref": rec.get("authorization_ref")})
            except (ConfigurationError, OSError):
                out["runs"].append({"stage": kind, "file": path.name, "error": "unreadable"})
    registries = {}
    for pointer in sorted((base.data / API_ID / "rel" / "registry").glob("*/current.json")):
        try:
            registries[pointer.parent.name] = parse_strict_json(
                pointer.read_bytes())["registry_revision"]
        except (ConfigurationError, OSError, KeyError):
            registries[pointer.parent.name] = "invalid"
    out["registry"] = registries or None
    return out
