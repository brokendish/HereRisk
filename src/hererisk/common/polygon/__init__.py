"""Shared Polygon Engine (Phase 4-K, minimal): geometric facts of a point against polygon rings.

* ``facts``         per-ring winding numbers on one ray, parity, normalised winding, H / H2, boundary
                    proximity, computed incrementally from ring pieces (no hazard knowledge)
* ``sqlite_reader`` the same facts from an existing diagnosis SQLite index (read only, chunk by chunk)

Facts only: nothing here decides inside / outside officially, adopts a diagnostic reading, or claims
the intent of the data's author. ADR-002, contract v0.2 (docs/api/polygon-engine-contract-v0.2.md).
No module here imports a hazard package (hererisk.flood etc.).
"""
