"""Published data snapshot for the public API (fixed at startup, elevation contract 7).

At startup every prefecture registry under ``rel/registry`` is read through a
read-only storage view (``rel/`` only), verified (pointer -> revision checksum
-> schema -> ids unique across registries) and every published entity is
checked against its registry checksum and the Validate profile. Any problem
means the service does not start. The snapshot is immutable; a new publication
becomes visible after an (approved) restart. Revisions / entities are
immutable files, so the snapshot stays valid while newer publications appear.

Selection: a dataset covers a point iff the point's XYZ tile at the dataset's
zoom equals the dataset's ``coverage.ref`` tile (same half-open pixel rule as
the lookup). Points outside the Web Mercator domain are covered by nothing
(never clamped / wrapped into it). A prefecture match alone never selects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hererisk.common.config import ConfigurationError, parse_strict_json
from hererisk.common.result import PipelineError
from hererisk.common.storage import PUBLISHED_READ_AREAS, ApiDataArea, Loc, StorageError
from hererisk.elevation.lookup.core import LAT_MAX, LON_MAX, LON_MIN, locate_pixel
from hererisk.elevation.publish import registry as reg
from hererisk.elevation.validate.core import CandidateRejected, validate_candidate

_PREF_RE = re.compile(r"^(0[1-9]|[1-3][0-9]|4[0-7])$")


class StartupError(Exception):
    """The published data cannot be served. The message is fixed and safe."""


@dataclass(frozen=True)
class PublishedDataset:
    dataset: dict[str, Any]  # registry entry (internal; never returned as is)
    tile: tuple[int, int, int]

    @property
    def id(self) -> str:
        return self.dataset["id"]


def _ms(timestamp: str) -> str:
    """Registry second-precision UTC -> public millisecond UTC format."""
    return timestamp[:-1] + ".000Z"


def public_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    """The only dataset information exposed by the API (elevation contract 4.1)."""
    return {
        "id": dataset["id"],
        "publication_version": dataset["publication"]["version"],
        "source": {"provider": dataset["source"]["provider"],
                   "page_url": dataset["source"].get("page_url")},
        "published_at": _ms(dataset["publication"]["published_at"]),
        "data_reference_date": None,
        "attribution": {"text": dataset["attribution"]["text"],
                        "license": dataset["attribution"]["license"],
                        "url": dataset["attribution"].get("url")},
    }


class PublishedSet:
    def __init__(self, area: ApiDataArea, datasets: tuple[PublishedDataset, ...]) -> None:
        self._area = area
        self.datasets = datasets

    @classmethod
    def load(cls, data_root: Path, *, allow_fixture_root: bool = False) -> PublishedSet:
        area = ApiDataArea(data_root, "elevation", writable=frozenset(),
                           readable=PUBLISHED_READ_AREAS)
        try:
            area.pin()
            if area.has_fixture_marker() and not allow_fixture_root:
                raise StartupError("fixture data roots are not served")
            datasets: list[PublishedDataset] = []
            for pref in area.list_dir(Loc(("rel", "registry"))):
                if not _PREF_RE.match(pref):
                    raise StartupError("unexpected entry in registry area")
                snapshot = reg.read_current(area, pref)
                if snapshot is None:
                    continue
                for dataset in snapshot.registry["datasets"]:
                    z, x, y = reg.tile_of(dataset)
                    data = reg.read_entity(area, dataset)
                    candidate = parse_strict_json(data)
                    validate_candidate(candidate, expected_tile={"z": z, "x": x, "y": y})
                    datasets.append(PublishedDataset(dataset, (z, x, y)))
            ids = [d.id for d in datasets]
            if len(ids) != len(set(ids)):
                raise StartupError("duplicate published dataset id")
        except StartupError:
            area.close()
            raise
        except (PipelineError, StorageError, ConfigurationError, CandidateRejected) as exc:
            area.close()
            raise StartupError("published data failed verification") from exc
        return cls(area, tuple(datasets))

    def covering(self, lat: float, lon: float) -> list[PublishedDataset]:
        if not (-LAT_MAX < lat <= LAT_MAX and LON_MIN <= lon < LON_MAX):
            return []  # outside the projection domain: covered by nothing
        found = []
        for published in self.datasets:
            z = published.tile[0]
            loc = locate_pixel(lat, lon, z)
            if (loc.z, loc.tile_x, loc.tile_y) == published.tile:
                found.append(published)
        return found

    def read_entity(self, published: PublishedDataset) -> bytes:
        return reg.read_entity(self._area, published.dataset)

    def close(self) -> None:
        self._area.close()
