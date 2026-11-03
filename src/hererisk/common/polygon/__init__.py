"""Shared Polygon Engine: geometric facts and official relations of a point against polygons.

* ``facts``         (Phase 4-K) per-ring winding numbers on one ray, parity, normalised winding, H / H2,
                    boundary proximity, computed incrementally from ring pieces (no hazard knowledge)
* ``sqlite_reader`` (Phase 4-K) the same facts from an existing diagnosis SQLite index (read only)
* ``validity``      (Phase 4-L) structure / coordinate checks and the validity class of each component
                    of a feature (GEOS; the flood index rules). Nothing is repaired
* ``relation``      (Phase 4-L) the official relation of a point to valid components (GEOS inside /
                    on_boundary / outside) and bounding-box ``pending_geometry`` for the others

``facts`` decides nothing officially. ``relation`` decides inside / outside only for valid polygons;
an invalid one is pending, never outside. Neither reads hazard attributes, merges components or says
"safe". ADR-002, contract v0.2 (docs/api/polygon-engine-contract-v0.2.md). No module here imports a
hazard package (hererisk.flood etc.); the product does not use this package yet.
"""
