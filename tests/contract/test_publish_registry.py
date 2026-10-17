"""Contract tests: Phase 1-D.4 Data Publish and Dataset Registry (test-only qualification).

Publications here use TEST-ONLY publish grants (tests/e2e_support.py) on test
data; a test publication is not the official publication of real GSI data.
"""

from __future__ import annotations

import hashlib
import json
import threading

import pytest

from e2e_support import TOKYO_TILES, World, centre, png_with, post
from hererisk.common.authorization import ExecutionContext
from hererisk.common.config import sha256_hex
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.orchestrator import DownloadPlan, DownloadRequest, _canonical_json
from hererisk.common.result import ModuleResult, Status
from hererisk.common.storage import ApiDataArea, StorageError
from hererisk.elevation.api.published import PublishedSet, StartupError
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.gsi_transport import GsiHttpTransport
from hererisk.elevation.normalize.stage import NormalizeStage
from hererisk.elevation.publish import registry as reg
from hererisk.elevation.publish.stage import PublishStage
from hererisk.elevation.validate.stage import ValidateStage

A, B = TOKYO_TILES
BODY_A = png_with({(10, 20): (0, 4, 210)})
BODY_B = png_with({(10, 20): (0, 0, 7)})


def modules(results):
    return [(r.module, r.status.value, r.error_code) for r in results]


def current(world):
    return json.loads((world.data_root / "elevation/rel/registry/13/current.json").read_bytes())


def registry(world):
    ptr = current(world)
    path = world.data_root / f"elevation/rel/registry/13/revisions/{ptr['registry_revision']}.json"
    return json.loads(path.read_bytes())


def tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# -- publish ------------------------------------------------------------------------------------
def test_publish_switches_registry_to_immutable_entities(tmp_path) -> None:
    world = World(tmp_path, {A: BODY_A, B: BODY_B})
    results = world.run()
    assert modules(results)[-1] == ("publish", "SUCCESS", None)
    run_id = results[0].run_id
    ptr = current(world)
    assert ptr["registry_revision"] == f"rev-{run_id}" and ptr["previous_revision"] is None
    doc = registry(world)
    assert doc["prefecture_code"] == "13" and doc["schema_version"] == "0.1"
    assert [d["id"] for d in doc["datasets"]] == [
        f"gsi-dem10b-candidate-z14-{A[0]}-{A[1]}", f"gsi-dem10b-candidate-z14-{B[0]}-{B[1]}"]
    for dataset, artifact in zip(doc["datasets"], results[2].artifacts):
        assert dataset["validation"] == {"status": "passed", "profile": "elevation-normalized-v0.1",
                                         "validated_at": dataset["validation"]["validated_at"]}
        assert dataset["publication"]["checksum"] == f"sha256:{artifact.sha256}"
        assert dataset["publication"]["format"] == "hererisk-elevation-cm-json-v0.1"
        assert dataset["attribution"]["license"].startswith("test-only")
        assert dataset["coverage"]["mode"] == "xyz_tile"
        entity = world.data_root / "elevation/rel" / dataset["publication"]["path"]
        candidate = world.data_root / f"elevation/work/normalized/{run_id}/{artifact.acquisition_id}.json"
        assert entity.read_bytes() == candidate.read_bytes()  # byte-identical copy
    publication = json.loads(
        (world.data_root / f"elevation/records/publications/{run_id}.json").read_bytes())
    assert publication["status"] == "SUCCESS"
    assert publication["authorization_ref"] == "test-only-not-an-approval-publish"
    assert publication["execution_context"] == "production"


def test_unpublished_candidates_are_not_visible(tmp_path) -> None:
    world = World(tmp_path, {A: BODY_A}, stages=(NormalizeStage(), ValidateStage()))
    assert modules(world.run())[-1] == ("validate", "SUCCESS", None)
    api = world.api()
    assert api._published.datasets == ()  # nothing published
    resp = post(api, dict(zip(("lat", "lon"), centre(*A, 10, 20))))
    assert resp.status == 200 and resp.json()["error"]["code"] == "no_coverage"


def test_validation_failure_prevents_publish(tmp_path) -> None:
    class FailingValidate(ValidateStage):
        def run(self, plan, previous, area, logger, *, authorization):
            return ModuleResult.error(plan.run_id, "validate", "VALIDATION_FAILED")

    world = World(tmp_path, {A: BODY_A}, stages=(NormalizeStage(), FailingValidate(), PublishStage()))
    results = world.run()
    assert modules(results)[-1] == ("validate", "FAILED", "VALIDATION_FAILED")
    assert not (world.data_root / "elevation/rel").exists()


def _plan_for(world: World, run_id: str) -> DownloadPlan:
    orch = world.orchestrator
    definition = orch._config.load("api", "elevation", "sources")
    auth = world.authorizer.authorize(api_id="elevation", operation="download",
                                      source_ref="gsi-dem10b-candidate", region_codes=("13",),
                                      definition=definition)
    request = DownloadRequest("elevation", ("13",), "gsi-dem10b-candidate")
    module = ElevationDownload(GsiHttpTransport(connection_factory=world.gsi))
    effective = _canonical_json(orch._effective_document(run_id, request, definition, auth, module))
    return DownloadPlan(run_id=run_id, api_id="elevation", source_ref="gsi-dem10b-candidate",
                        region_codes=("13",), definition=definition,
                        effective_configuration_ref=f"configurations/{run_id}/effective.json",
                        effective_configuration_sha256=sha256_hex(effective),
                        authorization=auth, resume=False)


def _validated(world: World):
    world.stages = (NormalizeStage(), ValidateStage())
    world.orchestrator._stages = {"elevation": world.stages}
    results = world.run()
    assert modules(results)[-1][1] == "SUCCESS"
    return results[-1], _plan_for(world, results[0].run_id)


def _publish(world, plan, validate_result, stage=None, area_cls=ApiDataArea):
    auth = world.authorizer.authorize(api_id="elevation", operation="publish",
                                      source_ref="gsi-dem10b-candidate", region_codes=("13",),
                                      definition=plan.definition)
    with area_cls(world.data_root, "elevation") as area:
        return (stage or PublishStage()).run(plan, validate_result, area,
                                             StructuredLogger(ListSink()), authorization=auth)


def test_publish_rejects_non_success_validation(tmp_path) -> None:
    world = World(tmp_path, {A: BODY_A})
    result, plan = _validated(world)
    failed = ModuleResult.error(plan.run_id, "validate", "VALIDATION_FAILED")
    assert _publish(world, plan, failed).error_code == "INVALID_INPUT"
    assert not (world.data_root / "elevation/rel").exists()


def test_failed_publish_keeps_old_registry(tmp_path) -> None:
    world = World(tmp_path, {A: BODY_A})
    first = world.run()
    old_pointer = current(world)
    old_files = tree(world.data_root / "elevation/rel")
    result, plan = _validated(world)

    class FailingSwitch(ApiDataArea):
        def replace_pointer(self, loc, data):
            raise StorageError("STORAGE_FULL", "injected")

    failed = _publish(world, plan, result, area_cls=FailingSwitch)
    assert failed.status is Status.FAILED and failed.error_code == "STORAGE_FULL"
    assert current(world) == old_pointer  # registry unchanged
    after = tree(world.data_root / "elevation/rel")
    assert all(after[k] == v for k, v in old_files.items())  # old entities intact
    api = world.api()
    doc = post(api, dict(zip(("lat", "lon"), centre(*A, 10, 20)))).json()
    assert doc["status"] == "success" and doc["dataset"]["publication_version"] == \
        f"pub-{first[0].run_id}"


@pytest.mark.parametrize("fail_on", ["revision", "entity"])
def test_failure_before_switch_publishes_nothing(tmp_path, fail_on) -> None:
    world = World(tmp_path, {A: BODY_A})
    result, plan = _validated(world)

    class Failing(ApiDataArea):
        def write_new(self, loc, data):
            if (fail_on == "revision" and "revisions" in loc) or \
                    (fail_on == "entity" and loc[:2] == ("rel", "versions")):
                raise StorageError("STORAGE_FULL", "injected")
            return super().write_new(loc, data)

    assert _publish(world, plan, result, area_cls=Failing).status is Status.FAILED
    assert not (world.data_root / "elevation/rel/registry/13/current.json").exists()
    assert world.api()._published.datasets == ()


def test_crash_after_switch_is_completed_on_rerun(tmp_path) -> None:
    world = World(tmp_path, {A: BODY_A})
    result, plan = _validated(world)

    class NoRecord(ApiDataArea):
        def write_new(self, loc, data):
            if loc[:2] == ("records", "publications"):
                raise StorageError("STORAGE_FULL", "injected")
            return super().write_new(loc, data)

    first = _publish(world, plan, result, area_cls=NoRecord)
    assert first.error_code == "RECORD_COMMIT_FAILED"
    assert current(world)["registry_revision"] == f"rev-{plan.run_id}"  # already effective
    revisions = sorted((world.data_root / "elevation/rel/registry/13/revisions").iterdir())
    again = _publish(world, plan, result)
    assert again.status is Status.SUCCESS
    assert sorted((world.data_root / "elevation/rel/registry/13/revisions").iterdir()) == revisions


def test_rerun_reuses_publication_without_changes(tmp_path) -> None:
    world = World(tmp_path, {A: BODY_A})
    first = world.run()
    before = tree(world.data_root)
    again = world.run(resume=first[0].run_id)
    assert again == first and tree(world.data_root) == before


def test_republish_keeps_old_generation(tmp_path) -> None:
    world = World(tmp_path, {A: BODY_A})
    first = world.run()
    old_revision = current(world)["registry_revision"]
    old_entity = registry(world)["datasets"][0]["publication"]["path"]
    second = world.run()
    ptr = current(world)
    assert ptr["previous_revision"] == old_revision
    assert registry(world)["datasets"][0]["publication"]["version"] == f"pub-{second[0].run_id}"
    assert (world.data_root / "elevation/rel" / old_entity).is_file()  # never deleted
    assert (world.data_root / f"elevation/rel/registry/13/revisions/{old_revision}.json").is_file()


def test_concurrent_publish_loses_no_update(tmp_path, monkeypatch) -> None:
    world_a = World(tmp_path / "a", {A: BODY_A})
    world_a.data_root = tmp_path / "shared"
    world_a.data_root.mkdir()
    world_a.orchestrator._data_root = world_a.data_root
    result_a, plan_a = _validated(world_a)
    world_b = World(tmp_path / "b", {B: BODY_B})
    world_b.data_root = world_a.data_root
    world_b.orchestrator._data_root = world_a.data_root
    result_b, plan_b = _validated(world_b)

    barrier = threading.Barrier(2, timeout=1.0)
    real = reg.read_current

    def racing(area, pref):
        snapshot = real(area, pref)
        try:
            barrier.wait()  # without the registry lock both would build on the same base
        except threading.BrokenBarrierError:
            pass
        return snapshot

    monkeypatch.setattr(reg, "read_current", racing)
    out = {}
    threads = [threading.Thread(target=lambda: out.setdefault("a", _publish(world_a, plan_a, result_a))),
               threading.Thread(target=lambda: out.setdefault("b", _publish(world_b, plan_b, result_b)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    monkeypatch.undo()
    assert out["a"].status is Status.SUCCESS and out["b"].status is Status.SUCCESS
    ids = {d["id"] for d in registry(world_a)["datasets"]}
    assert ids == {f"gsi-dem10b-candidate-z14-{A[0]}-{A[1]}",
                   f"gsi-dem10b-candidate-z14-{B[0]}-{B[1]}"}


# -- registry verification at API startup ---------------------------------------------------------
def _published_world(tmp_path):
    world = World(tmp_path, {A: BODY_A})
    world.run()
    return world


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda w: (w.data_root / "elevation/rel/registry/13/current.json").write_bytes(b"{"),
        lambda w: (w.data_root / "elevation/rel/registry/13/revisions" /
                   f"{current(w)['registry_revision']}.json").write_bytes(b"{}"),
        lambda w: next((w.data_root / "elevation/rel/versions").rglob("*.json")).write_bytes(b"{}"),
        lambda w: next((w.data_root / "elevation/rel/versions").rglob("*.json")).unlink(),
        lambda w: (w.data_root / "elevation/rel/registry/zz").mkdir(),
    ],
    ids=["pointer", "revision-checksum", "entity-checksum", "entity-missing", "unexpected-dir"],
)
def test_corrupt_registry_or_entities_refuse_startup(tmp_path, corrupt) -> None:
    world = _published_world(tmp_path)
    corrupt(world)
    with pytest.raises(StartupError):
        PublishedSet.load(world.data_root)


def test_fixture_data_root_is_not_served(harness) -> None:
    with pytest.raises(StartupError):
        PublishedSet.load(harness.data_root)
    PublishedSet.load(harness.data_root, allow_fixture_root=True).close()


def test_registry_area_is_not_writable_by_pipeline_areas(tmp_path) -> None:
    from hererisk.common.storage import Loc

    with ApiDataArea(tmp_path, "elevation") as area:  # default (Download/Normalize/Validate)
        for loc in (Loc(("rel", "versions", "x.json")), Loc(("rel", "registry", "13", "current.json"))):
            with pytest.raises(StorageError):
                area.write_new(loc, b"x")
            with pytest.raises(StorageError):
                area.replace_pointer(loc, b"x")
    readonly = ApiDataArea(tmp_path, "elevation", writable=frozenset(),
                           readable=frozenset({("rel", "versions"), ("rel", "registry")}))
    with readonly:
        with pytest.raises(StorageError):
            readonly.write_new(Loc(("rel", "versions", "x.json")), b"x")
        with pytest.raises(StorageError):
            readonly.read_bytes(Loc(("work", "normalized", "r", "x.json")), 10)


def test_valid_but_changed_entity_refuses_startup(tmp_path) -> None:
    """A still-valid candidate whose bytes differ from the registry checksum."""
    world = _published_world(tmp_path)
    path = next((world.data_root / "elevation/rel/versions").rglob("*.json"))
    data = path.read_bytes()
    path.unlink()
    path.write_bytes(data.replace(b"100", b"101", 1))
    with pytest.raises(StartupError):
        PublishedSet.load(world.data_root)


def test_publish_requires_publication_terms(tmp_path) -> None:
    from dataclasses import replace

    world = World(tmp_path, {A: BODY_A})
    result, plan = _validated(world)
    grant = world.authorizer.authorize(api_id="elevation", operation="publish",
                                       source_ref="gsi-dem10b-candidate", region_codes=("13",),
                                       definition=plan.definition)
    for policy in ({}, {"license": "x"}):
        auth = replace(grant, policy=policy)
        with ApiDataArea(world.data_root, "elevation") as area:
            out = PublishStage().run(plan, result, area, StructuredLogger(ListSink()),
                                     authorization=auth)
        assert out.status is Status.BLOCKED and out.error_code == "APPROVAL_REQUIRED"
    assert not (world.data_root / "elevation/rel").exists()
