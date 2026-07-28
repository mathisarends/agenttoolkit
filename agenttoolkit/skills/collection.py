import base64
import logging
from collections.abc import Iterator, Sequence
from html import escape
from pathlib import Path
from typing import Self

from agenttoolkit.skills.models import Skill, parse_skill
from agenttoolkit.skills.scripts import run_script

logger = logging.getLogger(__name__)


class Skills:
    def __init__(self, paths: Sequence[str | Path]) -> None:
        if not paths:
            raise ValueError("At least one skills directory is required.")
        self._skills: dict[str, Skill] = {}
        self._discover(tuple(Path(path) for path in paths))

    @classmethod
    def from_local_dir(cls, *paths: str | Path) -> Self:
        return cls(paths)

    @property
    def size(self) -> int:
        return len(self)

    @property
    def directories(self) -> tuple[Path, ...]:
        return tuple(skill.directory for skill in self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as error:
            available = ", ".join(self.names()) or "none"
            raise ValueError(
                f"Skill '{name}' not found. Available skills: {available}."
            ) from error

    def load(self, name: str) -> str:
        skill = self._current(name)
        files = "\n".join(
            f"<file>{escape(path)}</file>" for path in self._resource_paths(skill)
        )
        return (
            f'<skill_content name="{escape(skill.name)}">\n'
            f"# Skill: {skill.name}\n\n"
            f"{skill.instructions}\n\n"
            "<skill_files>\n"
            f"{files}\n"
            "</skill_files>\n"
            "</skill_content>"
        )

    def catalog(self) -> str:
        entries = "\n".join(
            (
                "<skill>\n"
                f"<name>{escape(skill.name)}</name>\n"
                f"<description>{escape(skill.description)}</description>\n"
                "</skill>"
            )
            for skill in self
        )
        if not entries:
            return ""
        return f"<available_skills>\n{entries}\n</available_skills>"

    def read_resource(self, name: str, path: str) -> str:
        skill = self._current(name)
        resource = self._resolve(skill, path)
        try:
            content = resource.read_bytes()
        except OSError as error:
            raise ValueError(
                f"Could not read resource '{path}' from skill '{name}': {error}"
            ) from error

        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return f"base64: {base64.b64encode(content).decode('ascii')}"

    async def run_script(
        self,
        name: str,
        path: str,
        args: Sequence[str] = (),
        timeout: int = 60,
    ) -> str:
        skill = self._current(name)
        script = self._resolve(skill, path)
        return await run_script(script, args, cwd=skill.directory, timeout=timeout)

    def __iter__(self) -> Iterator[Skill]:
        return iter(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def _current(self, name: str) -> Skill:
        discovered = self.get(name)
        skill = parse_skill(discovered.location)
        if skill.name != discovered.name:
            raise ValueError(
                f"Skill at '{discovered.location}' changed its name after discovery."
            )
        return skill

    def _discover(self, paths: tuple[Path, ...]) -> None:
        for configured_path in paths:
            root = configured_path.resolve()
            if not root.exists():
                raise ValueError(f"Skills directory does not exist: {root}")
            if not root.is_dir():
                raise ValueError(f"Skills path must be a directory: {root}")

            for directory in sorted(root.iterdir(), key=lambda item: item.name):
                skill_file = directory / "SKILL.md"
                if not directory.is_dir() or not skill_file.is_file():
                    continue
                resolved_skill_file = skill_file.resolve()
                if not resolved_skill_file.is_relative_to(root):
                    raise ValueError(
                        f"Skill file '{skill_file}' is outside configured "
                        f"root '{root}'."
                    )
                skill = parse_skill(resolved_skill_file)
                previous = self._skills.get(skill.name)
                if previous is not None:
                    logger.warning(
                        "Skill '%s' from %s overrides skill from %s.",
                        skill.name,
                        skill.directory,
                        previous.directory,
                    )
                self._skills[skill.name] = skill

    def _resource_paths(self, skill: Skill) -> list[str]:
        resources: list[str] = []
        for candidate in skill.directory.rglob("*"):
            if candidate.name == "SKILL.md" or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if resolved.is_relative_to(skill.directory):
                resources.append(resolved.relative_to(skill.directory).as_posix())
            else:
                logger.warning(
                    "Skipping skill resource outside base directory: %s",
                    candidate,
                )
        return sorted(resources)

    def _resolve(self, skill: Skill, resource_path: str) -> Path:
        candidate = Path(resource_path)
        if candidate.is_absolute():
            raise ValueError("Skill resource paths must be relative.")

        try:
            resolved = (skill.directory / candidate).resolve(strict=True)
        except OSError as error:
            available = self._resource_paths(skill)
            raise ValueError(
                f"Resource '{resource_path}' not found in skill '{skill.name}'. "
                f"Available resources: {available}."
            ) from error

        if not resolved.is_relative_to(skill.directory) or not resolved.is_file():
            raise ValueError(
                f"Resource '{resource_path}' is outside skill '{skill.name}'."
            )
        if resolved == skill.location:
            raise ValueError("Use load_skill to read SKILL.md.")
        return resolved
