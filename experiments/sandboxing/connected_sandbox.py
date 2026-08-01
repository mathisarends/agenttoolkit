import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from agenttoolkit.builtins.shell import (
    BindMount,
    DockerNetworkMode,
    DockerSandbox,
    SandboxPolicy,
)

load_dotenv()

_IMAGE = "agenttoolkit-connected:latest"
_CONNECTED_ENVIRONMENT = (
    "HUE_BRIDGE_IP",
    "HUE_APP_KEY",
    "SONOS_IP_ADDRESS",
    "SONOS_SPEAKER_NAME",
)
_SPOGO_CONFIG_DIR = "SPOGO_CONFIG_DIR"
_SPOGO_CONTAINER_DIR = "/workspace/.spogo"


def connected_sandbox(
    workspace: Path,
    *,
    require_spogo: bool = False,
    mounts: Sequence[BindMount] = (),
) -> DockerSandbox:
    spogo_config = _spogo_config_directory() / "config.toml"
    spogo_mounts = (
        (BindMount.read_write(spogo_config.parent, _SPOGO_CONTAINER_DIR),)
        if spogo_config.is_file()
        else ()
    )
    if require_spogo and not spogo_mounts:
        raise RuntimeError(
            f"Spogo is not authenticated: expected {spogo_config}. "
            "Run `spogo auth import` or `spogo auth paste` on the host first."
        )

    return DockerSandbox(
        _IMAGE,
        SandboxPolicy.for_workspace(
            workspace,
            writable=True,
            enable_network_access=True,
        ),
        mounts=(*mounts, *spogo_mounts),
        inherit_environment=_CONNECTED_ENVIRONMENT,
        user="host",
        network_mode=DockerNetworkMode.HOST,
        shell="/bin/bash",
    )


def _spogo_config_directory() -> Path:
    if configured := os.environ.get(_SPOGO_CONFIG_DIR):
        return Path(configured).expanduser()
    if app_data := os.environ.get("APPDATA"):
        return Path(app_data) / "spogo"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "spogo"
    if xdg_config_home := os.environ.get("XDG_CONFIG_HOME"):
        return Path(xdg_config_home) / "spogo"
    return Path.home() / ".config" / "spogo"
