#!/usr/bin/env python3
"""Production release steps, run on the VPS as the `deploy` user over SSH.

deploy.yml copies this script and both compose files into
$ROOT/releases/<sha>/ before calling it. The shared .env, releases.log and
every snapshot live outside the release directories.
"""

import argparse
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("VPS_ROOT", "/srv/geopoliticai"))
BACKUPS = Path(os.environ.get("VPS_BACKUPS", "/srv/backups"))
LOG = ROOT / "releases.log"
KEEP = 5
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# The nightly off-site copy. The bucket's 14-day lifecycle rule (README
# runbook) deletes old copies; backup() only uploads. aws-cli is pinned by
# digest to 2.22.35, the newest version OVH lists as compatible: later
# versions send checksum headers OVH Object Storage rejects
# (ovh/public-cloud-roadmap#781).
BUCKET = "dramatic-wieman"
S3_ENDPOINT = "https://s3.eu-west-par.io.cloud.ovh.net"
S3_REGION = "eu-west-par"
AWS_CLI = (
    "amazon/aws-cli:2.22.35"
    "@sha256:6977c83ae3dc99f28fcf8276b9ea5eec33833cd5be40574b34112e98113ec7a2"
)

# enter() pins the release directory and image tag for every later compose
# call, the way the bash original's `cd` and `export IMAGE_TAG` did.
_state: dict = {"cwd": None, "env": os.environ.copy()}


def compose_prefix() -> list[str]:
    """The docker compose invocation every command shares."""
    return [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
    ]


def compose(*args: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run a compose command in the pinned release; abort on failure."""
    return subprocess.run(
        [*compose_prefix(), *args],
        cwd=_state["cwd"],
        env=_state["env"],
        check=check,
        **kwargs,
    )


def compose_popen(*args: str, **kwargs) -> subprocess.Popen:
    """Start a compose command the caller streams to or from."""
    return subprocess.Popen(
        [*compose_prefix(), *args], cwd=_state["cwd"], env=_state["env"], **kwargs
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
# release's .snapshot names, and the :<sha> image tag each recorded release
# can still restart; everything else goes, or every deploy's three pulled
# images would fill the disk one release at a time.
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


# Stream pg_dump through gzip instead of buffering the whole dump in memory.
# A dump that dies partway through would still gzip into a valid-looking
# file, so a failed dump leaves no file behind to be trusted.
def dump(path: Path) -> None:
    proc = compose_popen(
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "geopoliticai",
        "geopoliticai",
        stdout=subprocess.PIPE,
    )
    stdout = proc.stdout
    try:
        assert stdout is not None
        with gzip.open(path, "wb") as zipped:
            shutil.copyfileobj(stdout, zipped)
    finally:
        if stdout is not None:
            stdout.close()
    if proc.wait() != 0:
        path.unlink(missing_ok=True)
        raise subprocess.CalledProcessError(proc.returncode, proc.args)


# Snapshot, migrate in README order, start. The old app containers keep
# serving until the final `up` (`run agentic-backend` does start the new
# phoenix early, through depends_on); a failure leaves them running for
# `discard`. The old `agentic-backend` is stopped before Alembic: on the
# 0002_checkpointer_to_agentic cutover its image has no search_path and, if
# it restarts, its setup() recreates an empty `public` copy of the
# checkpointer tables the new image then refuses to boot over.
def deploy(sha: str) -> None:
    # A retried deploy would overwrite the recorded release's .snapshot with
    # a post-release dump and turn rollback into a data-destroying trap;
    # redeploys go through the Rollback workflow instead.
    if sha in log_lines():
        print(
            f"{sha} is already recorded; deploy a new commit or use the "
            "rollback workflow",
            file=sys.stderr,
        )
        raise SystemExit(2)
    enter(sha)
    release = _state["cwd"]
    (release / ".snapshot").unlink(missing_ok=True)
    compose("pull")
    compose("up", "-d", "--no-build", "--wait", "postgres")
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    snapshot = BACKUPS / f"pre-{sha}-{stamp}.sql.gz"
    dump(snapshot)
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


# Load a snapshot into a side database, then swap it in. ALTER DATABASE ...
# RENAME cannot run inside a transaction block, so the swap is two
# autocommit renames: if the second fails, the first is renamed back, so a
# failed load or swap never leaves production without a database. The
# replaced one stays as geopoliticai_failed until the next restore. The
# users id sequence is moved past every id the replaced database handed out
# (its last_value, not max(id): an id issued to a user deleted later would
# otherwise be reused by the next signup, and a stale JWT could match that
# new account).
def restore(snapshot: Path) -> None:
    # gzip -t walks the whole file checking its CRC before anything is touched.
    with gzip.open(snapshot, "rb") as dump:
        while dump.read(1 << 20):
            pass
    compose(
        "exec",
        "-T",
        "postgres",
        "dropdb",
        "-U",
        "geopoliticai",
        "--if-exists",
        "geopoliticai_restore",
    )
    compose(
        "exec",
        "-T",
        "postgres",
        "createdb",
        "-U",
        "geopoliticai",
        "-O",
        "geopoliticai",
        "geopoliticai_restore",
    )
    with gzip.open(snapshot, "rb") as dump:
        load = compose_popen(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "geopoliticai",
            "geopoliticai_restore",
            stdin=subprocess.PIPE,
        )
        stdin = load.stdin
        assert stdin is not None
        shutil.copyfileobj(dump, stdin)
        stdin.close()
        if load.wait() != 0:
            raise subprocess.CalledProcessError(load.returncode, load.args)
    compose("stop", "agentic-backend", "web-backend", "frontend")
    compose(
        "exec",
        "-T",
        "postgres",
        "dropdb",
        "-U",
        "geopoliticai",
        "--if-exists",
        "geopoliticai_failed",
    )
    swap_databases()
    move_users_sequence()


# A pg_dump in the 03:15 backup or a manual psql session would make the
# renames fail with "database is being accessed by other users"; the app
# containers are already stopped, so whoever is left is terminated first.
SWAP_SQL = (
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    "WHERE datname IN ('geopoliticai', 'geopoliticai_restore', "
    "'geopoliticai_failed') AND pid <> pg_backend_pid()"
)


def swap_databases() -> None:
    args = [
        "exec",
        "-T",
        "postgres",
        "psql",
        "-q",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "geopoliticai",
        "-d",
        "postgres",
        "-c",
    ]
    compose(*args, SWAP_SQL)
    try:
        compose(*args, "ALTER DATABASE geopoliticai RENAME TO geopoliticai_failed")
        compose(*args, "ALTER DATABASE geopoliticai_restore RENAME TO geopoliticai")
    except subprocess.CalledProcessError:
        # The first rename already removed production, so put it back before
        # the error propagates: the old app containers restart against it.
        compose(
            *args,
            "ALTER DATABASE geopoliticai_failed RENAME TO geopoliticai",
            check=False,
        )
        raise


def move_users_sequence() -> None:
    last_value = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-At",
        "-U",
        "geopoliticai",
        "geopoliticai_failed",
        "-c",
        "SELECT coalesce(last_value, 0) FROM pg_sequences "
        "WHERE sequencename = 'users_user_id_seq'",
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    try:
        issued = int(last_value)
    except ValueError:
        # Only an absent sequence (a fresh database before any signup) reads
        # as empty; anything else fails the restore.
        raise OSError(f"could not read the users id sequence: {last_value!r}") from None
    if issued <= 0:
        return
    result = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-q",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "geopoliticai",
        "geopoliticai",
        "-c",
        f"SELECT setval(pg_get_serial_sequence('users_user', 'id'), {issued})",
        check=False,
    )
    if result.returncode != 0:
        print(
            "warning: the users id sequence was not moved past the replaced "
            "database; a deleted user's JWT could match a later signup",
            file=sys.stderr,
        )


# Best effort: something is already broken; the original error propagates.
def restart(sha: str) -> None:
    if not sha:
        return
    enter(sha)
    compose("up", "-d", "--no-build", "--wait", "--remove-orphans", check=False)


# Discard an unrecorded deploy: restore its snapshot, restart the previous release.
# The restore stops the app containers partway through, so a failure inside
# it must not leave the site down: the release that was serving is restarted
# best-effort before the error propagates.
def discard(sha: str) -> None:
    if sha in log_lines():
        print(f"{sha} is already recorded; use the rollback workflow", file=sys.stderr)
        raise SystemExit(2)
    prev = previous()
    try:
        enter(sha)
        marker = _state["cwd"] / ".snapshot"
        if marker.exists() and marker.stat().st_size > 0:
            restore(Path(marker.read_text().strip()))
        if prev:
            enter(prev)
            compose("up", "-d", "--no-build", "--wait", "--remove-orphans")
        else:
            compose("stop", "agentic-backend", "web-backend", "frontend")
    except subprocess.CalledProcessError:
        restart(prev)
        raise


# Go back to an earlier recorded release, restoring the snapshot taken just
# before the release that followed it. Everything written since is lost.
def rollback(target: str, confirm: str) -> None:
    if not SHA_RE.fullmatch(target):
        print(f"not a release sha: {target}", file=sys.stderr)
        raise SystemExit(2)
    next_sha = ""
    lines = log_lines()
    for index, line in enumerate(lines):
        if line == target and index + 1 < len(lines):
            next_sha = lines[index + 1]
            break
    if not next_sha:
        print(f"{target} is not an earlier release in {LOG}", file=sys.stderr)
        raise SystemExit(2)
    marker = ROOT / "releases" / next_sha / ".snapshot"
    snapshot = marker.read_text().strip()
    # Never print the expected value: the confirmation must come from the
    # deploy summary.
    if confirm != confirmation(snapshot):
        print(
            "confirmation does not match; copy it from the deploy summary",
            file=sys.stderr,
        )
        raise SystemExit(2)
    serve = previous()
    try:
        enter(next_sha)
        restore(Path(snapshot))
        # Record the undo before the target starts: if its `up` fails,
        # releases.log and current already describe reality and the workflows
        # can run again against the state on disk.
        write_log(lines[: lines.index(target) + 1])
        current = ROOT / "current"
        if current.is_symlink() or current.exists():
            current.unlink()
        current.symlink_to(ROOT / "releases" / target)
        enter(target)
        compose("up", "-d", "--no-build", "--wait", "--remove-orphans")
        prune()
    except subprocess.CalledProcessError:
        restart(serve)
        raise


# Nightly off-site copy of the production database, run by the deploy user's
# crontab against $ROOT/current. The dump lands in a local file first and
# is mounted into the aws-cli container, so only a complete dump is uploaded.
def backup() -> None:
    _state["cwd"] = ROOT / "current"
    fd, name = tempfile.mkstemp(prefix="nightly-", suffix=".sql.gz")
    os.close(fd)
    local = Path(name)
    try:
        dump(local)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--env-file",
                str(ROOT / "backup.env"),
                "-v",
                f"{local}:/dump.sql.gz:ro",
                AWS_CLI,
                "s3",
                "cp",
                "/dump.sql.gz",
                f"s3://{BUCKET}/nightly/{stamp}.sql.gz",
                "--endpoint-url",
                S3_ENDPOINT,
                "--region",
                S3_REGION,
            ],
            check=True,
        )
    finally:
        local.unlink(missing_ok=True)


def release_sha(value: str) -> str:
    """argparse type: a full 40-character commit sha."""
    if not SHA_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(f"not a release sha: {value}")
    return value


def main(argv: list[str]) -> int:
    """Run one command; bad arguments print usage and exit 2."""
    # Snapshots and logs may hold every user row; nothing this script writes
    # is world-readable.
    os.umask(0o077)

    parser = argparse.ArgumentParser(prog=Path(argv[0]).name)
    commands = parser.add_subparsers(dest="command", required=True)

    deploy_cmd = commands.add_parser("deploy", help="snapshot, migrate, start")
    deploy_cmd.add_argument("sha", type=release_sha)

    finish_cmd = commands.add_parser("finish", help="record a healthy release")
    finish_cmd.add_argument("sha", type=release_sha)

    discard_cmd = commands.add_parser("discard", help="undo a failed deploy")
    discard_cmd.add_argument("sha", type=release_sha)

    rollback_cmd = commands.add_parser(
        "rollback", help="go back to an earlier release, deleting newer data"
    )
    rollback_cmd.add_argument("target")
    rollback_cmd.add_argument("confirmation")

    commands.add_parser("backup", help="upload a nightly dump off-site")

    args = parser.parse_args(argv[1:])
    if args.command == "deploy":
        deploy(args.sha)
    elif args.command == "finish":
        finish(args.sha)
    elif args.command == "discard":
        discard(args.sha)
    elif args.command == "rollback":
        rollback(args.target, args.confirmation)
    elif args.command == "backup":
        backup()
    return 0


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
