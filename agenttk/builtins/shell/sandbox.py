from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from agenttk.builtins.shell.policy import SandboxPolicy


class SandboxError(Exception):
    pass


class SandboxUnavailableError(SandboxError):
    pass


class SandboxExecutionError(SandboxError):
    def __init__(self, result: SandboxResult) -> None:
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
class SandboxResult:
    command: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    output_truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0

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

    def check_returncode(self) -> SandboxResult:
        if not self.ok:
            raise SandboxExecutionError(self)
        return self


@runtime_checkable
class Sandbox(Protocol):
    @property
    def policy(self) -> SandboxPolicy: ...

    async def execute(
        self,
        command: str,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | bytes | None = None,
        timeout: float | None = None,
    ) -> SandboxResult: ...


async def run_process(
    argv: Sequence[str],
    *,
    command: str,
    cwd: Path | None,
    env: Mapping[str, str] | None,
    stdin: str | bytes | None,
    timeout: float | None,
    max_output_bytes: int | None,
) -> SandboxResult:
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
        raise SandboxUnavailableError(f"executable not found: {argv[0]}") from error

    stdout = bytearray()
    stderr = bytearray()
    captured = 0
    truncated = False

    async def read_stream(
        stream: asyncio.StreamReader | None,
        destination: bytearray,
    ) -> None:
        nonlocal captured, truncated
        if stream is None:
            return
        while chunk := await stream.read(64 * 1024):
            if max_output_bytes is None:
                destination.extend(chunk)
                continue
            remaining = max_output_bytes - captured
            if remaining > 0:
                kept = chunk[:remaining]
                destination.extend(kept)
                captured += len(kept)
            if len(chunk) > max(remaining, 0):
                truncated = True

    async def communicate() -> int:
        readers = [
            asyncio.create_task(read_stream(process.stdout, stdout)),
            asyncio.create_task(read_stream(process.stderr, stderr)),
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
    except asyncio.CancelledError:
        await _terminate_process(process)
        raise
    except BaseException:
        await _terminate_process(process)
        raise

    duration = time.monotonic() - started
    return SandboxResult(
        command=command,
        returncode=returncode,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
        duration_seconds=duration,
        timed_out=timed_out,
        output_truncated=truncated,
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
