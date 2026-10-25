"""Provider interface, the default (not connected) providers and the synthetic sample providers.

A provider is any object with an ``id`` (str) and ``lookup(lat, lon) -> dict`` that returns one
section in the contract shape (docs/api/location-api-v0.1.md section 5). Providers do not know
about each other. Connection points for real data are listed in the contract, section 8.

The sample providers exist only for local screen checks. They are enabled only by
``--sample-data`` (loopback only), every section carries ``synthetic: true`` and every name says
that it is synthetic. They never describe the real point.
"""

from __future__ import annotations

from typing import Any, Protocol

from hererisk.location.model import AVAILABLE, HAZARDS, NO_MATCH, UNKNOWN, not_available_section


class Provider(Protocol):
    id: str

    def lookup(self, lat: float, lon: float) -> dict[str, Any]: ...


class NotConnected:
    """Default provider: the data is not connected yet."""

    def __init__(self, provider_id: str) -> None:
        self.id = provider_id

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        return not_available_section(self.id)


def default_providers() -> dict[str, Provider]:
    """Address (future: MLIT 位置参照情報), elevation (future: GSI), four hazards: all not connected."""
    out: dict[str, Provider] = {"address": NotConnected("address"), "elevation": NotConnected("elevation")}
    out.update({h: NotConnected(h) for h in HAZARDS})
    return out


# ---- synthetic sample providers (development only) ------------------------------------------

_SAMPLE_NOTE = "合成データ（画面確認用）。実在の地点の情報ではありません。"


def _sample_source(n: int) -> dict[str, Any]:
    return {"source_id": f"synthetic-source-{n}", "organization": "サンプル機関（架空）",
            "title": f"サンプルデータ{n}（架空）", "data_version": "sample", "synthetic": True}


class _Sample:
    def __init__(self, provider_id: str, section: dict[str, Any]) -> None:
        self.id = provider_id
        self._section = section

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        return {"provider": self.id, "synthetic": True, "sample_note": _SAMPLE_NOTE, **self._section}


def sample_providers() -> dict[str, Provider]:
    """One example of each state, so that a screen can show all of them."""
    return {
        "address": _Sample("address-sample", {
            "status": AVAILABLE,
            "result": {"display_name": "サンプル県架空市見本町1丁目（合成データ）", "precision": "chome",
                       "method": "nearest_representative_point", "is_confirmed_address": False},
            "source": _sample_source(0)}),
        "elevation": _Sample("elevation-sample", {
            "status": AVAILABLE, "result": {"elevation_m": 3.2, "unit": "m"}, "source": _sample_source(0)}),
        "flood": _Sample("flood-sample", {
            "status": AVAILABLE,
            "results": [   # two official results, kept separate: no maximum, no representative value
                {"source": _sample_source(1), "feature_ref": "synthetic-f1",
                 "original_class": {"code": "3", "label": "3.0m以上5.0m未満（架空）"}},
                {"source": _sample_source(2), "feature_ref": "synthetic-f2",
                 "original_class": {"code": "2", "label": "0.5m以上3.0m未満（架空）"}}]}),
        "tsunami": _Sample("tsunami-sample", {
            "status": NO_MATCH, "results": [], "searched_sources": [_sample_source(3)]}),
        "storm_surge": _Sample("storm_surge-sample", {
            "status": UNKNOWN, "results": None, "reason": "invalid_geometry_in_source"}),
        "landslide": NotConnected("landslide"),
    }
