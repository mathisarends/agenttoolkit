import logging
from collections.abc import Iterator, Sequence
from html import escape
from pathlib import Path
from typing import Self

from agenttoolkit.skills.models import LoadedSkill, Skill, SkillChanges, parse_skill

logger = logging.getLogger(__name__)


class Skills:
    def __init__(self, paths: Sequence[str | Path]) -> None:
        if not paths:
            raise ValueError("At least one skills directory is required.")
        self._paths = tuple(Path(path).resolve() for path in paths)
        self._skills = self._discover(self._paths)
        self._revision = 0
        self._fingerprint = self._source_fingerprint()

    @classmethod
    def from_local_dir(cls, *paths: str | Path) -> Self:
        return cls(paths)

    @property
    def size(self) -> int:
        return len(self)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def directories(self) -> tuple[Path, ...]:
        return tuple(skill.directory for skill in self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills)

    def refresh(self) -> SkillChanges:
        """Refresh the registry from the configured skills directories."""
        skills = self._discover(self._paths)
        added = tuple(sorted(skills.keys() - self._skills.keys()))
        removed = tuple(sorted(self._skills.keys() - skills.keys()))
        updated = tuple(
            sorted(
                name
                for name in skills.keys() & self._skills.keys()
                if skills[name] != self._skills[name]
            )
        )
        if added or updated or removed:
            self._revision += 1
        self._skills = skills
        self._fingerprint = self._source_fingerprint()
        return SkillChanges(
            revision=self._revision,
            added=added,
            updated=updated,
            removed=removed,
        )

    def refresh_if_changed(self) -> SkillChanges:
        """Refresh only when skill document paths or metadata changed."""
        if self._source_fingerprint() == self._fingerprint:
            return SkillChanges(revision=self._revision)
        return self.refresh()

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as error:
            available = ", ".join(self.names()) or "none"
            raise ValueError(
                f"Skill '{name}' not found. Available skills: {available}."
            ) from error

    def load(self, name: str) -> LoadedSkill:
        skill = self._current(name)
        return LoadedSkill(
            name=skill.name,
            instructions=skill.instructions,
            directory=skill.directory,
            resources=tuple(self._resource_paths(skill)),
        )

    def render_prompt(self) -> str:
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

    def _discover(self, paths: tuple[Path, ...]) -> dict[str, Skill]:
        skills: dict[str, Skill] = {}
        for configured_path in paths:
            root = configured_path
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
                previous = skills.get(skill.name)
                if previous is not None:
                    logger.warning(
                        "Skill '%s' from %s overrides skill from %s.",
                        skill.name,
                        skill.directory,
                        previous.directory,
                    )
                skills[skill.name] = skill
        return skills

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

    def _source_fingerprint(self) -> tuple[tuple[str, int, int], ...]:
        fingerprint: list[tuple[str, int, int]] = []
        for root_index, root in enumerate(self._paths):
            try:
                directories = tuple(root.iterdir())
            except OSError:
                return ((f"{root_index}:<unavailable>", -1, -1),)
            for directory in directories:
                skill_file = directory / "SKILL.md"
                try:
                    metadata = skill_file.stat()
                except OSError:
                    continue
                if not directory.is_dir() or not skill_file.is_file():
                    continue
                relative_path = skill_file.relative_to(root).as_posix()
                fingerprint.append(
                    (
                        f"{root_index}:{relative_path}",
                        metadata.st_mtime_ns,
                        metadata.st_size,
                    )
                )
        return tuple(sorted(fingerprint))
