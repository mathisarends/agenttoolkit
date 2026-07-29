from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath
from typing import cast

import pytest

import agenttoolkit.builtins.shell.backends.docker as docker_backend
from agenttoolkit.builtins.shell import (
    BindMount,
    BubblewrapSandbox,
    DockerNetworkMode,
    DockerSandbox,
    Sandbox,
    SandboxExecutionError,
    SandboxLimits,
    SandboxPolicy,
    SandboxResult,
    SandboxUnavailableError,
    UnsafeLocalSandbox,
)


def test_policy_normalizes_paths_network_and_environment(tmp_path: Path) -> None:
    policy = SandboxPolicy.for_workspace(
        tmp_path,
        enable_network_access=True,
        environment={"COUNT": "2"},
    )

    assert policy.enable_network_access
    assert policy.allows_read(tmp_path / "child")
    assert policy.allows_write(tmp_path / "child")
    assert policy.environment["COUNT"] == "2"
    assert policy.validate_working_directory(None) == tmp_path.resolve()
    child = tmp_path / "child"
    child.mkdir()
    assert policy.validate_working_directory("child") == child.resolve()

    readonly = SandboxPolicy(
        working_directory=tmp_path,
        readable_paths=(tmp_path, tmp_path),
        enable_network_access=False,
    )
    assert not readonly.enable_network_access
    assert len(readonly.readable_paths) == 1
    assert not readonly.allows_write(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeout_seconds", 0),
        ("max_output_bytes", -1),
        ("memory_bytes", 0),
        ("pids", -2),
        ("cpus", 0),
    ],
)
def test_limits_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        SandboxLimits(**{field: value})


def test_policy_rejects_bad_environment_and_working_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="variable name"):
        SandboxPolicy(environment={"BAD=NAME": "value"})
    with pytest.raises(ValueError, match="contains NUL"):
        SandboxPolicy(environment={"NAME": "bad\0value"})

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    policy = SandboxPolicy.for_workspace(root)
    with pytest.raises(PermissionError, match="not allowed"):
        policy.validate_working_directory(outside)
    with pytest.raises(NotADirectoryError):
        policy.validate_working_directory(root / "missing")


def test_sandbox_result_helpers() -> None:
    success = SandboxResult("true", 0, "out", "err", 0.1)
    assert success.ok
    assert success.exit_code == 0
    assert success.output == "out\nerr"
    assert success.check_returncode() is success

    failure = SandboxResult("false", 2, "", "bad", 0.1)
    with pytest.raises(SandboxExecutionError, match="status 2: bad"):
        failure.check_returncode()

    timeout = SandboxResult("wait", -1, "", "", 1.0, timed_out=True)
    with pytest.raises(SandboxExecutionError, match="timed out"):
        timeout.check_returncode()


@pytest.mark.asyncio
async def test_unsafe_local_sandbox_executes_and_enforces_output_limit(
    tmp_path: Path,
) -> None:
    policy = SandboxPolicy.for_workspace(
        tmp_path,
        limits=SandboxLimits(timeout_seconds=2, max_output_bytes=3),
        environment={"FROM_POLICY": "yes"},
    )
    sandbox = UnsafeLocalSandbox(
        policy,
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    assert isinstance(sandbox, Sandbox)

    result = await sandbox.execute(
        "import os,sys; print(os.environ['FROM_POLICY']); "
        "print(os.environ['EXTRA']); print(sys.stdin.read())",
        env={"EXTRA": "ok"},
        stdin="input",
    )
    assert result.ok
    assert result.output_truncated
    assert len(result.stdout.encode()) <= 3


@pytest.mark.asyncio
async def test_unsafe_local_sandbox_timeout_errors_and_validation(
    tmp_path: Path,
) -> None:
    sandbox = UnsafeLocalSandbox(
        SandboxPolicy.for_workspace(
            tmp_path,
            limits=SandboxLimits(timeout_seconds=0.01),
        ),
        shell=sys.executable,
        shell_arguments=("-c",),
    )
    result = await sandbox.execute("import time; time.sleep(1)")
    assert result.timed_out
    assert not result.ok

    with pytest.raises(ValueError, match="must not be empty"):
        await sandbox.execute("")
    with pytest.raises(ValueError, match="positive"):
        await sandbox.execute("pass", timeout=0)

    missing = UnsafeLocalSandbox(shell="definitely-not-an-executable")
    with pytest.raises(SandboxUnavailableError, match="executable not found"):
        await missing.execute("echo ok", cwd=tmp_path)


def test_docker_builds_a_hardened_command(tmp_path: Path) -> None:
    extra = tmp_path / "read"
    extra.mkdir()
    policy = SandboxPolicy(
        working_directory=tmp_path,
        readable_paths=(extra,),
        writable_paths=(tmp_path,),
        enable_network_access=False,
        limits=SandboxLimits(memory_bytes=1024, pids=8, cpus=0.5),
        environment={"BASE": "one"},
    )
    sandbox = DockerSandbox("python:3.14", policy)
    argv = sandbox.build_argv(
        "python -V",
        env={"EXTRA": "two"},
        interactive=True,
    )

    assert argv[:3] == ("docker", "run", "--rm")
    assert "--read-only" in argv
    assert ("--network", "none") == argv[
        argv.index("--network") : argv.index("--network") + 2
    ]
    assert "--memory" in argv
    assert "--pids-limit" in argv
    assert "--cpus" in argv
    assert "-i" in argv
    assert "BASE=one" in argv
    assert "EXTRA=two" in argv
    assert argv[-1] == "python -V"
    assert str(sandbox.container_path("read")) == "/mnt/path-0"


def test_docker_supports_named_mounts_inherited_environment_and_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setenv("CLI_TOKEN", "secret")
    monkeypatch.setattr(docker_backend.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(docker_backend.os, "getgid", lambda: 1001, raising=False)

    config_mount = BindMount.read_only(config, "/home/agent/.config/my-cli")
    output_mount = BindMount.read_write(output, "/output")
    sandbox = DockerSandbox(
        "cli:latest",
        SandboxPolicy.for_workspace(workspace),
        mounts=(config_mount, output_mount),
        inherit_environment=("CLI_TOKEN", "CLI_TOKEN"),
        user="host",
    )
    argv = sandbox.build_argv("my-cli build")

    assert sandbox.mounts == (config_mount, output_mount)
    assert sandbox.inherit_environment == ("CLI_TOKEN",)
    assert sandbox.user == "host"
    assert ("--env", "CLI_TOKEN") == argv[argv.index("--env") : argv.index("--env") + 2]
    assert "CLI_TOKEN=secret" not in argv
    assert ("--user", "1000:1001") == argv[
        argv.index("--user") : argv.index("--user") + 2
    ]
    assert (
        f"type=bind,src={config.resolve()},dst=/home/agent/.config/my-cli,readonly"
    ) in argv
    assert f"type=bind,src={output.resolve()},dst=/output" in argv
    assert sandbox.container_path(config / "settings.json") == PurePosixPath(
        "/home/agent/.config/my-cli/settings.json"
    )
    assert sandbox.container_path(output / "artifact.txt") == PurePosixPath(
        "/output/artifact.txt"
    )


def test_docker_supports_an_explicit_network_mode(tmp_path: Path) -> None:
    sandbox = DockerSandbox(
        "cli:latest",
        SandboxPolicy.for_workspace(tmp_path, enable_network_access=True),
        network_mode=DockerNetworkMode.HOST,
    )

    argv = sandbox.build_argv("cli status")

    assert sandbox.network_mode is DockerNetworkMode.HOST
    assert ("--network", "host") == argv[
        argv.index("--network") : argv.index("--network") + 2
    ]


def test_docker_validates_convenience_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()

    with pytest.raises(ValueError, match="absolute container path"):
        BindMount.read_only(first, "relative")
    with pytest.raises(ValueError, match="below '/'"):
        BindMount.read_write(first, "/")
    with pytest.raises(ValueError, match="source is configured more than once"):
        DockerSandbox(
            "image",
            mounts=(
                BindMount.read_only(first, "/first"),
                BindMount.read_only(first, "/other"),
            ),
        )
    with pytest.raises(ValueError, match="target is configured more than once"):
        DockerSandbox(
            "image",
            mounts=(
                BindMount.read_only(first, "/shared"),
                BindMount.read_only(second, "/shared"),
            ),
        )
    with pytest.raises(ValueError, match="variable name"):
        DockerSandbox("image", inherit_environment=("BAD=NAME",))
    with pytest.raises(ValueError, match="user"):
        DockerSandbox("image", user=" ")
    with pytest.raises(TypeError, match="DockerNetworkMode"):
        DockerSandbox("image", network_mode=cast(DockerNetworkMode, "host"))
    with pytest.raises(ValueError, match="requires network access"):
        DockerSandbox("image", network_mode=DockerNetworkMode.HOST)

    monkeypatch.delenv("MISSING_CLI_TOKEN", raising=False)
    sandbox = DockerSandbox(
        "image",
        SandboxPolicy.for_workspace(workspace),
        inherit_environment=("MISSING_CLI_TOKEN",),
    )
    with pytest.raises(ValueError, match="MISSING_CLI_TOKEN"):
        sandbox.build_argv("true")

    collision = DockerSandbox(
        "image",
        SandboxPolicy.for_workspace(workspace),
        mounts=(BindMount.read_only(first, "/workspace"),),
    )
    with pytest.raises(ValueError, match="used by both"):
        collision.build_argv("true")


def test_docker_validates_image_command_mounts_and_cwd(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="image"):
        DockerSandbox(" ")

    sandbox = DockerSandbox("image", SandboxPolicy.for_workspace(tmp_path))
    with pytest.raises(ValueError, match="command"):
        sandbox.build_argv("")

    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    with pytest.raises(PermissionError):
        sandbox.build_argv("pwd", cwd=outside)

    missing = tmp_path / "missing"
    policy = SandboxPolicy(
        working_directory=tmp_path,
        readable_paths=(missing,),
    )
    with pytest.raises(FileNotFoundError):
        DockerSandbox("image", policy).build_argv("true", cwd=tmp_path)


@pytest.mark.asyncio
async def test_docker_cleans_up_a_timed_out_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run_process(
        argv: tuple[str, ...],
        **_: object,
    ) -> SandboxResult:
        calls.append(argv)
        return SandboxResult(
            "command",
            1,
            "",
            "",
            1,
            timed_out=argv[1] == "run",
        )

    monkeypatch.setattr(docker_backend, "run_process", fake_run_process)
    sandbox = DockerSandbox("image", SandboxPolicy.for_workspace(tmp_path))
    result = await sandbox.execute("sleep 100")

    assert result.timed_out
    assert sandbox.policy.working_directory == tmp_path.resolve()
    assert calls[0][1] == "run"
    name = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ("docker", "rm", "--force", name)


@pytest.mark.asyncio
async def test_docker_preserves_unavailable_error_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def unavailable(*_: object, **__: object) -> SandboxResult:
        nonlocal calls
        calls += 1
        raise SandboxUnavailableError("missing")

    monkeypatch.setattr(docker_backend, "run_process", unavailable)
    sandbox = DockerSandbox("image", SandboxPolicy.for_workspace(tmp_path))
    with pytest.raises(SandboxUnavailableError):
        await sandbox.execute("true")
    assert calls == 1


def test_bubblewrap_builds_policy_and_rejects_unsupported_limits(
    tmp_path: Path,
) -> None:
    policy = SandboxPolicy.for_workspace(
        tmp_path,
        enable_network_access=True,
        environment={"NAME": "value"},
    )
    sandbox = BubblewrapSandbox(policy)
    argv = sandbox.build_argv("echo ok")
    assert "--unshare-all" in argv
    assert "--share-net" in argv
    assert "--bind" in argv
    assert "--clearenv" in argv
    assert "NAME" in argv
    assert argv[-1] == "echo ok"

    with pytest.raises(ValueError, match="command"):
        sandbox.build_argv("")
    limited = SandboxPolicy.for_workspace(
        tmp_path,
        limits=SandboxLimits(memory_bytes=1024),
    )
    with pytest.raises(ValueError, match="cannot enforce"):
        BubblewrapSandbox(limited).build_argv("true")


@pytest.mark.asyncio
async def test_bubblewrap_reports_unavailable_when_not_installed(
    tmp_path: Path,
) -> None:
    sandbox = BubblewrapSandbox(
        SandboxPolicy.for_workspace(tmp_path),
        executable="definitely-not-bwrap",
    )
    assert not sandbox.available
    with pytest.raises(SandboxUnavailableError, match="only available"):
        await sandbox.execute("true")
