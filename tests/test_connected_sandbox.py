from pathlib import Path

import pytest

from experiments.sandboxing import connected_sandbox

_CONNECTED_ENVIRONMENT = (
    "HUE_BRIDGE_IP",
    "HUE_APP_KEY",
    "SONOS_IP_ADDRESS",
    "SONOS_SPEAKER_NAME",
)


@pytest.mark.parametrize("missing_name", _CONNECTED_ENVIRONMENT)
def test_connected_sandbox_rejects_missing_forwarded_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    monkeypatch.setenv("SPOGO_CONFIG_DIR", str(tmp_path / "spogo"))
    for name in _CONNECTED_ENVIRONMENT:
        monkeypatch.setenv(name, "configured")
    monkeypatch.delenv(missing_name)

    sandbox = connected_sandbox(tmp_path)

    with pytest.raises(
        ValueError,
        match=f"host environment variable is not set: {missing_name}",
    ):
        sandbox.build_argv("true")


def test_connected_sandbox_uses_host_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOGO_CONFIG_DIR", str(tmp_path / "spogo"))
    for name in _CONNECTED_ENVIRONMENT:
        monkeypatch.setenv(name, "configured")

    argv = connected_sandbox(tmp_path).build_argv("sonos discover")

    assert ("--network", "host") == argv[
        argv.index("--network") : argv.index("--network") + 2
    ]
