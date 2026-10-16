"""Real-process tests: SIGKILL at each commit point, and cross-process exclusion.

A child process runs the Orchestrator and kills itself with SIGKILL (no
finally / atexit / buffered flush runs) at a chosen point. The parent then
re-runs the same run_id and checks the outcome. Real network access is
blocked inside the child as well.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

import fixture_builder as fb
from hererisk.common.result import Status
from hererisk.common.storage import ApiDataArea

RUN_ID = "33333333-3333-4333-8333-333333333333"

_WORKER = r'''
import os, signal, socket, sys
from pathlib import Path
def _deny(*a, **k): raise RuntimeError("network forbidden")
socket.socket.connect = _deny; socket.getaddrinfo = _deny; socket.create_connection = _deny
from conftest import Harness
from hererisk.common.logging import ListSink
from hererisk.common.orchestrator import DownloadRequest
from hererisk.common.storage import ApiDataArea
from hererisk.elevation.download.transport import FixtureTransport

fixture, data, point, run_id = sys.argv[1:]
fixture, data = Path(fixture), Path(data)
def die(): os.kill(os.getpid(), signal.SIGKILL)

class Area(ApiDataArea):
    def finish_file(self, handle):
        super().finish_file(handle)
        if point == "complete": die()
    def link_no_clobber(self, src, dst):
        super().link_no_clobber(src, dst)
        if point == "artifact": die()
    def write_new(self, loc, data):
        super().write_new(loc, data)
        if point == "record" and "/records/acquisitions/" in str(loc): die()
        if point == "marker" and "/records/commits/" in str(loc): die()

class Transport(FixtureTransport):
    def _read(self, handle):
        if point == "part":
            with handle:
                yield handle.read(4096)
                die()
        yield from super()._read(handle)

h = Harness(fixture, data, ListSink(), Transport(fixture / "tiles"), area_factory=Area)
orch = h.orchestrator()
orch._id_factory = lambda: run_id
orch.run_download(DownloadRequest("elevation", ("13",), "fixture-dem-png-tokyo"))
if point == "return": die()
sys.exit(7)
'''


def _env() -> dict[str, str]:
    paths = [str(fb.REPO_ROOT / "src"), str(fb.REPO_ROOT / "tests")]
    return dict(os.environ, PYTHONPATH=os.pathsep.join(paths))


@pytest.mark.parametrize(
    "point,expected",
    [
        ("part", "RECOVERY_REQUIRED"),
        ("complete", "RECOVERY_REQUIRED"),
        ("artifact", "RECOVERY_REQUIRED"),
        ("record", "RECOVERY_REQUIRED"),
        ("marker", "SUCCESS"),  # first tile committed, second acquired on resume
        ("return", "SUCCESS"),  # everything committed, result lost
    ],
)
def test_sigkill_then_resume(harness, point, expected) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _WORKER, str(harness.fixture_root), str(harness.data_root),
         point, RUN_ID],
        env=_env(), capture_output=True, timeout=60, check=False,
    )
    assert proc.returncode == -signal.SIGKILL, (proc.returncode, proc.stderr[-2000:])
    before = harness.files()
    result = harness.run(resume=RUN_ID)
    if expected == "SUCCESS":
        assert result.status is Status.SUCCESS, result
        assert len(result.artifacts) == 2
        expected_urls = (["https://fixture.invalid/dem_png/14/14551/6450.png"]
                         if point == "marker" else [])
        assert harness.transport.requested_urls == expected_urls
    else:
        assert result.status is Status.BLOCKED and result.error_code == expected, result
        assert harness.transport.requested_urls == []
        assert harness.files() == before
    assert not (harness.api_root / "dl").exists() and not (harness.api_root / "rel").exists()


def test_lock_held_by_other_process(harness) -> None:
    code = (
        "import sys\nfrom pathlib import Path\nfrom conftest import Harness\n"
        "from hererisk.common.logging import ListSink\n"
        "from hererisk.elevation.download.transport import FixtureTransport\n"
        "f, d = map(Path, sys.argv[1:])\n"
        "print(Harness(f, d, ListSink(), FixtureTransport(f / 'tiles')).run().error_code)\n"
    )
    with ApiDataArea(harness.data_root, "elevation") as area:
        lock = area.path("work", "locks", "download-fixture-dem-png-tokyo.lock")
        with area.exclusive_lock(lock):
            proc = subprocess.run(
                [sys.executable, "-c", code, str(harness.fixture_root), str(harness.data_root)],
                env=_env(), capture_output=True, text=True, timeout=60, check=False,
            )
    assert proc.returncode == 0 and proc.stdout.strip() == "TARGET_BUSY", proc.stderr
    assert harness.run().status is Status.SUCCESS
