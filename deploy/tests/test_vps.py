"""Exercises vps.py against a stub `docker` in a temp root: no Docker daemon,
no VPS. Run: uvx pytest deploy/tests"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

VPS = Path(__file__).resolve().parent.parent / "vps.py"
STALE_IMAGE = f"ghcr.io/rafalsliwinski3991/geopoliticai-frontend:{0:040d}"
RESTORED = "RENAME TO geopoliticai_failed"
# Logs every call, fails any call containing $FAIL_ON, and answers the few
# calls whose output vps.py reads.
STUB_DOCKER = f"""#!{sys.executable}
import os, sys
args = " ".join(sys.argv[1:])
with open(os.environ["DOCKER_LOG"], "a") as log:
    log.write(f"IMAGE_TAG={{os.environ.get('IMAGE_TAG', '')}} {{args}}\\n")
# Only the snapshot load reads stdin; `psql -c` calls do not.
if "psql" in args and " -c " not in args:
    sys.stdin.buffer.read()
if os.environ.get("FAIL_ON") and os.environ["FAIL_ON"] in args:
    sys.exit(1)
if "pg_dump" in args:
    print("-- dump")
if "pg_sequences" in args:
    print(7)
if "images --format" in args:
    print("{STALE_IMAGE}")
    print("ghcr.io/rafalsliwinski3991/geopoliticai-frontend:latest")
"""


def sha(n: int) -> str:
    return f"{n:040d}"


class Vps:
    def __init__(self, tmp: Path) -> None:
        self.root = tmp / "root"
        self.backups = tmp / "backups"
        self.docker_log = tmp / "docker.log"
        self.tmpdir = tmp / "tmp"
        self.tmpdir.mkdir()
        self.root.mkdir()
        (self.root / ".env").touch()
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(STUB_DOCKER)
        docker.chmod(0o755)
        self.env = {
            **os.environ,
            "VPS_ROOT": str(self.root),
            "VPS_BACKUPS": str(self.backups),
            "DOCKER_LOG": str(self.docker_log),
            "TMPDIR": str(self.tmpdir),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        }

    def run(self, *args: str, fail_on: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VPS), *args],
            env={**self.env, "FAIL_ON": fail_on},
            capture_output=True,
            check=False,
            text=True,
        )

    def ship(self, n: int) -> None:
        (self.root / "releases" / sha(n)).mkdir(parents=True, exist_ok=True)

    def release(self, n: int) -> str:
        """Deploy and record release n; return the finish summary."""
        self.ship(n)
        assert self.run("deploy", sha(n)).returncode == 0
        finished = self.run("finish", sha(n))
        assert finished.returncode == 0
        return finished.stdout

    def docker_calls(self) -> str:
        return self.docker_log.read_text() if self.docker_log.exists() else ""

    def clear_docker_log(self) -> None:
        self.docker_log.write_text("")

    def recorded(self) -> list[str]:
        return (self.root / "releases.log").read_text().splitlines()

    def current(self) -> Path:
        return (self.root / "current").readlink()

    def snapshots(self) -> list[Path]:
        return list(self.backups.glob("pre-*"))


@pytest.fixture
def vps(tmp_path: Path) -> Vps:
    return Vps(tmp_path)


def confirmation(summary: str) -> str:
    return summary.split("confirm=")[1].strip()


def test_finish_prunes_to_the_newest_five_releases(vps: Vps) -> None:
    # Arrange
    for n in range(1, 6):
        vps.release(n)
    vps.ship(6)
    assert vps.run("deploy", sha(6)).returncode == 0
    # A leftover snapshot from an earlier, retried attempt of the same release.
    (vps.backups / f"pre-{sha(6)}-19700101T0000Z.sql.gz").touch()

    # Act
    finished = vps.run("finish", sha(6))

    # Assert
    assert finished.returncode == 0
    assert vps.recorded() == [sha(n) for n in range(2, 7)]
    assert not (vps.root / "releases" / sha(1)).exists()
    assert len(vps.snapshots()) == 5
    assert vps.current() == vps.root / "releases" / sha(6)
    assert f"target={sha(5)} confirm=delete-data-since-" in finished.stdout


def test_prune_drops_unrecorded_image_tags_but_never_latest(vps: Vps) -> None:
    # Arrange
    vps.ship(1)
    vps.run("deploy", sha(1))

    # Act
    vps.run("finish", sha(1))

    # Assert
    removed = [line for line in vps.docker_calls().splitlines() if "image rm" in line]
    assert any(STALE_IMAGE in line for line in removed)
    assert not any(line.endswith(":latest") for line in removed)


def test_failed_pg_dump_leaves_no_snapshot(vps: Vps) -> None:
    # Arrange
    vps.ship(1)

    # Act
    deployed = vps.run("deploy", sha(1), fail_on="pg_dump")

    # Assert
    assert deployed.returncode != 0
    assert vps.snapshots() == []
    assert not (vps.root / "releases" / sha(1) / ".snapshot").exists()


def test_discard_after_failed_migration_restores_and_restarts_previous(
    vps: Vps,
) -> None:
    # Arrange
    vps.release(1)
    vps.ship(2)
    assert vps.run("deploy", sha(2), fail_on="alembic upgrade").returncode != 0
    vps.clear_docker_log()

    # Act
    discarded = vps.run("discard", sha(2))

    # Assert
    assert discarded.returncode == 0
    calls = vps.docker_calls()
    assert RESTORED in calls
    assert f"IMAGE_TAG={sha(1)} compose" in calls
    assert "up -d --no-build --wait" in calls
    assert "setval(pg_get_serial_sequence('users_user', 'id'), 7)" in calls
    assert vps.recorded() == [sha(1)]


def test_discard_before_snapshot_restores_nothing(vps: Vps) -> None:
    # Arrange
    vps.release(1)
    vps.ship(2)
    assert vps.run("deploy", sha(2), fail_on=" pull").returncode != 0
    vps.clear_docker_log()

    # Act
    discarded = vps.run("discard", sha(2))

    # Assert
    assert discarded.returncode == 0
    assert RESTORED not in vps.docker_calls()


def test_discard_refuses_a_recorded_release(vps: Vps) -> None:
    # Arrange
    vps.release(1)

    # Act
    discarded = vps.run("discard", sha(1))

    # Assert
    assert discarded.returncode == 2
    assert "use the rollback workflow" in discarded.stderr


def test_rollback_with_wrong_confirmation_changes_nothing(vps: Vps) -> None:
    # Arrange
    vps.release(1)
    vps.release(2)
    vps.clear_docker_log()

    # Act
    rolled = vps.run("rollback", sha(1), "delete-data-since-19700101T0000Z")

    # Assert
    assert rolled.returncode == 2
    assert RESTORED not in vps.docker_calls()
    assert vps.current() == vps.root / "releases" / sha(2)


def test_rollback_restores_and_goes_back(vps: Vps) -> None:
    # Arrange
    vps.release(1)
    summary = vps.release(2)
    vps.clear_docker_log()

    # Act
    rolled = vps.run("rollback", sha(1), confirmation(summary))

    # Assert
    assert rolled.returncode == 0
    assert RESTORED in vps.docker_calls()
    assert vps.recorded() == [sha(1)]
    assert vps.current() == vps.root / "releases" / sha(1)


def test_rollback_rejects_a_corrupt_snapshot_before_touching_anything(
    vps: Vps,
) -> None:
    # Arrange
    vps.release(1)
    summary = vps.release(2)
    (snapshot,) = vps.backups.glob(f"pre-{sha(2)}-*.sql.gz")
    with snapshot.open("r+b") as file:
        file.truncate(1)
    vps.clear_docker_log()

    # Act
    rolled = vps.run("rollback", sha(1), confirmation(summary))

    # Assert
    assert rolled.returncode != 0
    assert RESTORED not in vps.docker_calls()
    assert vps.recorded() == [sha(1), sha(2)]
    assert vps.current() == vps.root / "releases" / sha(2)


def test_backup_uploads_a_complete_dump(vps: Vps) -> None:
    # Arrange
    vps.release(1)
    (vps.root / "backup.env").touch()
    vps.clear_docker_log()

    # Act
    backed_up = vps.run("backup")

    # Assert
    assert backed_up.returncode == 0
    upload = next(line for line in vps.docker_calls().splitlines() if "s3 cp" in line)
    assert "amazon/aws-cli:2.22.35@sha256:" in upload
    assert ":/dump.sql.gz:ro" in upload
    assert "s3 cp /dump.sql.gz s3://dramatic-wieman/nightly/" in upload
    assert list(vps.tmpdir.iterdir()) == []


def test_backup_never_uploads_a_failed_dump(vps: Vps) -> None:
    # Arrange
    vps.release(1)
    (vps.root / "backup.env").touch()
    vps.clear_docker_log()

    # Act
    backed_up = vps.run("backup", fail_on="pg_dump")

    # Assert
    assert backed_up.returncode != 0
    assert "s3 cp" not in vps.docker_calls()
    assert list(vps.tmpdir.iterdir()) == []


def _load_vps_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("vps_under_test", VPS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dump_raises_when_pg_dump_has_no_stdout_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    module = _load_vps_module()
    monkeypatch.setattr(
        module, "compose_popen", lambda *a, **k: subprocess.Popen(["true"])
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="no stdout pipe"):
        module.dump(tmp_path / "out.sql.gz")


def test_restore_raises_when_psql_has_no_stdin_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    import gzip

    module = _load_vps_module()
    snapshot = tmp_path / "s.sql.gz"
    with gzip.open(snapshot, "wb") as handle:
        handle.write(b"-- dump")
    monkeypatch.setattr(module, "compose", lambda *a, **k: None)
    monkeypatch.setattr(
        module, "compose_popen", lambda *a, **k: subprocess.Popen(["true"])
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="no stdin pipe"):
        module.restore(snapshot)
