"""Pins the code sandbox's isolation in the production Compose files (README,
"Code sandbox"). Reads them as text: no Docker, no YAML library, never `.env`.

The reader knows only the two-space block layout these files use. A setting
written any other way reads as changed, which fails the test.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASE_FILE = "docker-compose.yml"
PROD_FILE = "docker-compose.prod.yml"
SANDBOX = "mcp-server"
SANDBOX_PEERS = {"mcp-server", "agentic-backend"}
SANDBOX_NETWORK = """\
internal: true
enable_ipv6: false
driver_opts:
  com.docker.network.bridge.gateway_mode_ipv4: isolated"""
ISOLATION = {
    "networks": "[sandbox]",
    "init": "true",
    "read_only": "true",
    "tmpfs": "- /dev/shm:size=1m,mode=0755",
    "cap_drop": "[ALL]",
    "cap_add": "[SETUID, SETGID, KILL]",
    "security_opt": '["no-new-privileges:true"]',
    "sysctls": """\
fs.mqueue.queues_max: "0"
kernel.shmmni: "0"
kernel.msgmni: "0"
kernel.sem: "0 0 0 0\"""",
    "mem_limit": "384m",
    "memswap_limit": "384m",
    "cpus": "1",
    "pids_limit": "256",
}
# Keys that run or watch the service and give its code nothing more.
HARMLESS_KEYS = {"build", "image", "healthcheck"}


def read_mapping(block: str) -> dict[str, str]:
    """Return each key of a YAML block mapping with its value as text."""
    entries: dict[str, list[str]] = {}
    key = ""
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(" "):
            entries[key].append(line[2:])
            continue
        key, _, inline = line.partition(":")
        assert key not in entries, f"{key} is written twice"
        entries[key] = [inline.strip()] if inline.strip() else []
    return {key: "\n".join(value) for key, value in entries.items()}


def read_compose(name: str) -> dict[str, str]:
    return read_mapping((REPO / name).read_text())


def read_services(name: str) -> dict[str, dict[str, str]]:
    services = read_mapping(read_compose(name)["services"])
    return {service: read_mapping(block) for service, block in services.items()}


@pytest.mark.parametrize("setting", ISOLATION)
def test_the_sandbox_keeps_each_isolation_setting(setting: str) -> None:
    """Each setting closes one way out for model-written code; without it the
    stack still starts and every other test still passes."""
    # Arrange
    expected = ISOLATION[setting]

    # Act
    sandbox = read_services(BASE_FILE)[SANDBOX]

    # Assert
    assert sandbox.get(setting) == expected


def test_the_sandbox_is_given_nothing_beyond_its_isolation_settings() -> None:
    """An `env_file`, volume, port, or `privileged` would hand model-written code
    a secret, state, or a way out."""
    # Arrange
    allowed = set(ISOLATION) | HARMLESS_KEYS

    # Act
    sandbox = read_services(BASE_FILE)[SANDBOX]

    # Assert
    assert set(sandbox) - allowed == set()


def test_the_sandbox_network_has_no_route_out_and_no_host_address() -> None:
    """`internal` alone leaves a host address through which sandbox code reaches
    host services; `isolated` removes it."""
    # Arrange
    # Act
    networks = read_mapping(read_compose(BASE_FILE)["networks"])

    # Assert
    assert networks["sandbox"] == SANDBOX_NETWORK


@pytest.mark.parametrize("name", [BASE_FILE, PROD_FILE])
def test_only_the_api_shares_the_sandbox_network(name: str) -> None:
    """Every service on the network can be called by sandbox code, so Postgres,
    Phoenix, and the web backend stay off it."""
    # Arrange
    # Act
    services = read_services(name)

    # Assert
    members = {
        service
        for service, settings in services.items()
        if re.search(r"\bsandbox\b", settings.get("networks", ""))
    }
    assert members <= SANDBOX_PEERS


def test_production_only_adds_a_restart_policy_to_the_sandbox() -> None:
    """The production file is merged over the base one, so any other key there
    widens the sandbox on the live site only."""
    # Arrange
    # Act
    sandbox = read_services(PROD_FILE)[SANDBOX]

    # Assert
    assert sandbox == {"restart": "unless-stopped"}


def test_production_redefines_no_network() -> None:
    """A top-level block in the production file, `networks` or an `include`,
    could undo the sandbox network without touching the base file."""
    # Arrange
    # Act
    production = read_compose(PROD_FILE)

    # Assert
    assert list(production) == ["services"]
