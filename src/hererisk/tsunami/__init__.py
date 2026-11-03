"""Tsunami inundation data (Phase 4-M): registration, the A40 format adapter, the local search index and
its independent check against the GML of the same ZIP.

The Location API ``hazards.tsunami`` section is served by ``hererisk.location.tsunami_provider`` from an
index built here (``python -m hererisk.tsunami build``), only when started with ``--tsunami-index``.
Validity and the point relation come from the shared Polygon Engine (``hererisk.common.polygon``).
Local verification only: nothing here is a publication, and the usage terms are not approved.
"""
