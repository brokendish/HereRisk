"""Public elevation HTTP API (Phase 1-E): POST /api/v1/elevation.

Reads only the published Dataset Registry and published entities
(rel/registry, rel/versions) through a read-only storage view. It never imports
or calls Download / Normalize / Validate / Publish operations, the GSI PoC or the
network client, and never accesses GSI at run time.
"""
