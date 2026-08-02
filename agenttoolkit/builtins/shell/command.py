from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol, runtime_checkable

from agenttoolkit.builtins.shell.execution import DEFAULT_TIMEOUT, CommandTimeout


class CommandError(Exception):
    pass


class CommandUnavailableError(CommandError):
    pass


class CommandExecutionError(CommandError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        detail = result.stderr.strip() or result.stdout.strip()
        message = (
            f"command timed out after {result.duration_seconds:.2f}s"
            if result.timed_out
            else f"command exited with status {result.returncode}"
        )
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    stdout_omitted_bytes: int = 0
    stderr_omitted_bytes: int = 0
    stdout_spill_path: Path | None = None
    stderr_spill_path: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0

    @property
    def output_truncated(self) -> bool:
        return bool(self.stdout_omitted_bytes or self.stderr_omitted_bytes)

    @property
    def spill_paths(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in (self.stdout_spill_path, self.stderr_spill_path)
            if path is not None
        )

    @property
    def exit_code(self) -> int | None:
        return self.returncode

    @property
    def output(self) -> str:
        if not self.stderr:
            return self.stdout
        if not self.stdout:
            return self.stderr
        separator = "" if self.stdout.endswith("\n") else "\n"
        return f"{self.stdout}{separator}{self.stderr}"

    def check_returncode(self) -> CommandResult:
        if not self.ok:
            raise CommandExecutionError(self)
        return self


@runtime_checkable
class CommandRunner(Protocol):
    """Executes shell commands without making isolation or lifecycle claims."""

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: CommandTimeout = DEFAULT_TIMEOUT,
    ) -> CommandResult: ...


class _StreamCapture:
    """Keeps the first and last bytes of a stream and drops the middle.

    A head-only cap would discard the end, which is where a long run usually
    reports its failure. The spill file is only opened once the budget
    overflows.
    """

    def __init__(self, max_bytes: int | None, spill_path: Path | None) -> None:
        self._head_budget = None if max_bytes is None else max_bytes - max_bytes // 2
        self._tail_budget = None if max_bytes is None else max_bytes // 2
        self._spill_path = spill_path
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0
        self._spill: IO[bytes] | None = None
        self._spill_seeded = False

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._total += len(chunk)
        if self._head_budget is None or self._tail_budget is None:
            self._head.extend(chunk)
            return

        if self._spill is not None:
            self._spill.write(chunk)

        room = self._head_budget - len(self._head)
        if room > 0:
            self._head.extend(chunk[:room])
            chunk = chunk[room:]
            if not chunk:
                return

        self._tail.extend(chunk)
        overflow = len(self._tail) - self._tail_budget
        if overflow <= 0:
            return
        # Nothing has been dropped yet, so head + tail is still the complete
        # stream and can seed the spill file before the middle goes away.
        self._open_spill()
        del self._tail[:overflow]

    def finish(self) -> tuple[str, int, Path | None]:
        self.close()
        omitted = self._total - len(self._head) - len(self._tail)
        if omitted <= 0:
            return (self._head + self._tail).decode(errors="replace"), 0, None

        spilled = self._spill_path if self._spill_opened else None
        marker = _omission_marker(omitted, spilled)
        text = (
            self._head.decode(errors="replace")
            + marker
            + self._tail.decode(errors="replace")
        )
        return text, omitted, spilled

    def close(self) -> None:
        if self._spill is not None:
            self._spill.close()
            self._spill = None

    @property
    def _spill_opened(self) -> bool:
        return self._spill is not None or self._spill_seeded

    def _open_spill(self) -> None:
        if self._spill_path is None or self._spill_seeded:
            return
        self._spill_path.parent.mkdir(parents=True, exist_ok=True)
        self._spill = self._spill_path.open("wb")
        self._spill_seeded = True
        self._spill.write(self._head)
        self._spill.write(self._tail)


def _omission_marker(omitted: int, spill_path: Path | None) -> str:
    detail = f"... {_format_bytes(omitted)} omitted"
    if spill_path is not None:
        detail = f"{detail}; full output: {spill_path}"
    return f"\n[{detail} ...]\n"


def _format_bytes(count: int) -> str:
    if count < 1024:
        return f"{count} B"
    size = count / 1024
    for unit in ("KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


async def run_process(
    argv: Sequence[str],
    *,
    command: str,
    cwd: Path | None,
    env: Mapping[str, str] | None,
    stdin: str | bytes | None,
    timeout: float | None,
    max_output_bytes: int | None,
    spill_directory: Path | None = None,
) -> CommandResult:
    if not argv:
        raise ValueError("argv must not be empty")
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive or None")

    input_bytes = stdin.encode() if isinstance(stdin, str) else stdin
    started = time.monotonic()
    creation_flags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creation_flags,
            start_new_session=os.name == "posix",
        )
    except FileNotFoundError as error:
        raise CommandUnavailableError(f"executable not found: {argv[0]}") from error

    if spill_directory is None:
        stdout_spill: Path | None = None
        stderr_spill: Path | None = None
    else:
        spill_id = uuid.uuid4().hex[:12]
        stdout_spill = spill_directory / f"{spill_id}.stdout.log"
        stderr_spill = spill_directory / f"{spill_id}.stderr.log"

    # Each stream gets its own budget: a chatty stdout must not be able to
    # crowd out the stderr that explains why the command failed.
    stdout_capture = _StreamCapture(max_output_bytes, stdout_spill)
    stderr_capture = _StreamCapture(max_output_bytes, stderr_spill)

    async def read_stream(
        stream: asyncio.StreamReader | None,
        capture: _StreamCapture,
    ) -> None:
        if stream is None:
            return
        while chunk := await stream.read(64 * 1024):
            capture.feed(chunk)

    async def communicate() -> int:
        readers = [
            asyncio.create_task(read_stream(process.stdout, stdout_capture)),
            asyncio.create_task(read_stream(process.stderr, stderr_capture)),
        ]
        try:
            if input_bytes is not None and process.stdin is not None:
                try:
                    process.stdin.write(input_bytes)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()
            await asyncio.gather(*readers)
            return await process.wait()
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)

    timed_out = False
    try:
        returncode = await asyncio.wait_for(communicate(), timeout=timeout)
    except TimeoutError:
        timed_out = True
        await _terminate_process(process)
        returncode = process.returncode
    except BaseException:
        await _terminate_process(process)
        stdout_capture.close()
        stderr_capture.close()
        raise

    stdout_text, stdout_omitted, stdout_path = stdout_capture.finish()
    stderr_text, stderr_omitted, stderr_path = stderr_capture.finish()
    duration = time.monotonic() - started
    return CommandResult(
        command=command,
        returncode=returncode,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_seconds=duration,
        timed_out=timed_out,
        stdout_omitted_bytes=stdout_omitted,
        stderr_omitted_bytes=stderr_omitted,
        stdout_spill_path=stdout_path,
        stderr_spill_path=stderr_path,
    )


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        except FileNotFoundError:
            pass

    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()
