import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from agenttoolkit.builtins.shell.policy import SandboxPolicy
from agenttoolkit.builtins.shell.sandbox import SandboxResult, run_process


class UnsafeLocalSandbox:
    """Runs locally; path and network policy fields are intentionally not enforced."""

    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        *,
        shell: str = "bash",
        shell_arguments: Sequence[str] = ("-lc",),
    ) -> None:
        self._policy = policy or SandboxPolicy(enable_network_access=True)
        self._shell = shell
        self._shell_arguments = tuple(shell_arguments)

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: float | None = None,
    ) -> SandboxResult:
        if not command:
            raise ValueError("command must not be empty")

        selected_cwd = self._policy.validate_working_directory(cwd)
        selected_env = dict(os.environ)
        selected_env.update(self._policy.environment)
        if env:
            selected_env.update(env)

        return await run_process(
            (self._shell, *self._shell_arguments, command),
            command=command,
            cwd=Path(selected_cwd),
            env=selected_env,
            stdin=stdin,
            timeout=(
                self._policy.limits.timeout_seconds if timeout is None else timeout
            ),
            max_output_bytes=self._policy.limits.max_output_bytes,
        )
