#!/usr/bin/env python3
"""Production release steps, run on the VPS as the `deploy` user over SSH.

deploy.yml copies this script and both compose files into
$ROOT/releases/<sha>/ before calling it. The shared .env, releases.log and
every snapshot live outside the release directories.
"""

import gzip
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("VPS_ROOT", "/srv/geopoliticai"))
BACKUPS = Path(os.environ.get("VPS_BACKUPS", "/srv/backups"))
LOG = ROOT / "releases.log"
KEEP = 5
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# enter() pins the release directory and image tag for every later compose
# call, the way the bash original's `cd` and `export IMAGE_TAG` did.
_state: dict = {"cwd": None, "env": os.environ.copy()}


def compose(*args: str) -> None:
    """Run a compose command in the pinned release; abort on failure."""
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.prod.yml",
            *args,
        ],
        cwd=_state["cwd"],
        env=_state["env"],
        check=True,
    )


def compose_stdout(*args: str) -> subprocess.Popen:
    """Start a compose command whose stdout is streamed by the caller."""
    return subprocess.Popen(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.prod.yml",
            *args,
        ],
        cwd=_state["cwd"],
        env=_state["env"],
        stdout=subprocess.PIPE,
    )


def enter(sha: str) -> None:
    """cd into a release directory and pin its image tag."""
    release = ROOT / "releases" / sha
    env_link = release / ".env"
    if env_link.is_symlink() or env_link.exists():
        env_link.unlink()
    env_link.symlink_to(ROOT / ".env")
    _state["cwd"] = release
    _state["env"]["IMAGE_TAG"] = sha


def log_lines() -> list[str]:
    """The recorded releases, oldest first; an absent log reads as empty."""
    return LOG.read_text().splitlines() if LOG.exists() else []


def write_log(lines: list[str]) -> None:
    """Replace releases.log atomically (write a temporary, then rename)."""
    tmp = LOG.with_name(LOG.name + ".tmp")
    tmp.write_text("".join(line + "\n" for line in lines))
    tmp.replace(LOG)


def previous() -> str:
    """The last recorded release, or an empty string when none is."""
    lines = log_lines()
    return lines[-1] if lines else ""


def confirmation(snapshot: str) -> str:
    """pre-<sha>-20260923T1402Z.sql.gz -> delete-data-since-20260923T1402Z"""
    timestamp = snapshot.rsplit("-", 1)[1]
    return f"delete-data-since-{timestamp.removesuffix('.sql.gz')}"


# Keep the newest $KEEP releases, their directories, the one snapshot each
# release's .snapshot names (retried deploys leave older ones behind), and the
# :<sha> image tag each recorded release can still restart; everything else
# goes, or every deploy's three pulled images would fill the disk.
def prune() -> None:
    keep = log_lines()[-KEEP:]
    write_log(keep)
    kept_snapshots: set[str] = set()
    releases = ROOT / "releases"
    if releases.is_dir():
        for directory in releases.iterdir():
            if not directory.is_dir():
                continue
            if directory.name in keep:
                marker = directory / ".snapshot"
                if marker.exists():
                    kept_snapshots.add(marker.read_text().strip())
            else:
                shutil.rmtree(directory)
    if BACKUPS.is_dir():
        for snapshot in BACKUPS.glob("pre-*.sql.gz"):
            if str(snapshot) not in kept_snapshots:
                snapshot.unlink()
    tags = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    ).stdout.splitlines()
    for image in tags:
        repo, _, tag = image.rpartition(":")
        if "geopoliticai-" not in repo or tag == "latest" or tag in keep:
            continue
        if SHA_RE.fullmatch(tag):
            # Still-in-use images may refuse; that keeps them restartable.
            subprocess.run(["docker", "image", "rm", image], check=False)


# Snapshot, migrate in README order, start. The old app containers keep
# serving until the final `up` (`run agentic-backend` does start the new
# phoenix early, through depends_on); a failure leaves them running for
# `abort`. The old `agentic-backend` is stopped before Alembic: on the
# 0002_checkpointer_to_agentic cutover its image has no search_path and, if it
# restarts, its setup() recreates an empty `public` copy of the checkpointer
# tables the new image then refuses to boot over.
def deploy(sha: str) -> None:
    enter(sha)
    release = _state["cwd"]
    (release / ".snapshot").unlink(missing_ok=True)
    compose("pull")
    compose("up", "-d", "--no-build", "--wait", "postgres")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    snapshot = BACKUPS / f"pre-{sha}-{stamp}.sql.gz"
    # Stream pg_dump through gzip instead of buffering the whole dump in
    # memory; a failed dump leaves no snapshot file behind to be trusted.
    dump = compose_stdout(
        "exec", "-T", "postgres", "pg_dump", "-U", "geopoliticai", "geopoliticai"
    )
    stdout = dump.stdout
    try:
        assert stdout is not None
        with gzip.open(snapshot, "wb") as zipped:
            shutil.copyfileobj(stdout, zipped)
    finally:
        if stdout is not None:
            stdout.close()
    if dump.wait() != 0:
        snapshot.unlink(missing_ok=True)
        raise subprocess.CalledProcessError(dump.returncode, dump.args)
    (release / ".snapshot").write_text(str(snapshot))
    compose(
        "run",
        "--rm",
        "web-backend",
        ".venv/bin/python",
        "manage.py",
        "migrate",
        "--noinput",
    )
    compose(
        "run",
        "--rm",
        "web-backend",
        ".venv/bin/python",
        "manage.py",
        "createcachetable",
    )
    compose("stop", "agentic-backend")
    compose("run", "--rm", "agentic-backend", ".venv/bin/alembic", "upgrade", "head")
    compose("up", "-d", "--no-build", "--wait", "--remove-orphans")


# Record a release that passed the public health check.
def finish(sha: str) -> None:
    prev = previous()
    enter(sha)
    write_log([line for line in log_lines() if line != sha] + [sha])
    current = ROOT / "current"
    if current.is_symlink() or current.exists():
        current.unlink()
    current.symlink_to(ROOT / "releases" / sha)
    prune()
    if prev and prev != sha:
        snapshot = (_state["cwd"] / ".snapshot").read_text().strip()
        print(
            f"Rollback to the previous release: target={prev} confirm={confirmation(snapshot)}"
        )
    else:
        print("No earlier release to roll back to.")


def main(argv: list[str]) -> int:
    """Dispatch one command; anything else prints usage and exits 2."""
    # Snapshots and logs may hold every user row; nothing this script writes
    # is world-readable.
    os.umask(0o077)
    commands = {"deploy": deploy, "finish": finish}
    command = argv[1] if len(argv) > 1 else ""
    name = Path(argv[0]).name
    if command in commands:
        sha = argv[2] if len(argv) > 2 else ""
        if not SHA_RE.fullmatch(sha):
            print(f"usage: {name} {command} <sha>", file=sys.stderr)
            return 2
        commands[command](sha)
        return 0
    print(f"usage: {name} deploy|finish <sha>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode or 1)
    except (OSError, EOFError) as error:
        # A corrupt snapshot or a missing release file must not traceback on
        # the operator; gzip and the filesystem both surface through here.
        print(f"{Path(sys.argv[0]).name}: {error}", file=sys.stderr)
        sys.exit(1)
