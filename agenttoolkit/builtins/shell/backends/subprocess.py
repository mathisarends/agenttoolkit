import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from agenttoolkit.builtins.shell.command import CommandResult, run_process
from agenttoolkit.builtins.shell.execution import CommandDefaults


class LocalShellRunner:
    """Executes shell commands directly on the host without isolation."""

    def __init__(
        self,
        defaults: CommandDefaults | None = None,
        *,
        shell: str = "bash",
        shell_arguments: Sequence[str] = ("-lc",),
    ) -> None:
        self._defaults = defaults or CommandDefaults()
        self._shell = shell
        self._shell_arguments = tuple(shell_arguments)

    @property
    def defaults(self) -> CommandDefaults:
        return self._defaults

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        if not command:
            raise ValueError("command must not be empty")

        selected_cwd = self._defaults.select_working_directory(cwd)
        selected_env = dict(os.environ)
        selected_env.update(self._defaults.environment)
        if env:
            selected_env.update(env)

        return await run_process(
            (self._shell, *self._shell_arguments, command),
            command=command,
            cwd=Path(selected_cwd),
            env=selected_env,
            stdin=stdin,
            timeout=(
                self._defaults.limits.timeout_seconds if timeout is None else timeout
            ),
            max_output_bytes=self._defaults.limits.max_output_bytes,
        )
