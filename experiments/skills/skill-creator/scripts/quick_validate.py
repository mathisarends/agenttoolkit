#!/usr/bin/env python3
"""Validate the structure and frontmatter of one skill folder."""

import argparse
import re
from pathlib import Path

import yaml

_MAX_NAME_LENGTH = 64
_MAX_DESCRIPTION_LENGTH = 1024
_NAME_PATTERN = re.compile(r"^(?!.*--)[a-z0-9]+(?:-[a-z0-9]+)*$")
_TODO_PATTERN = re.compile(
    r"""(?m)^(?:description:\s*["']?\[?TODO\b|(?:\d+\.\s+)TODO:)"""
)
_FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z",
    re.DOTALL,
)
_ALLOWED_FIELDS = frozenset(
    {
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
    }
)


def _validate_name(name: object, directory_name: str) -> list[str]:
    if not isinstance(name, str) or not name.strip():
        return ["name must be a non-empty string"]

    name = name.strip()
    errors = []
    if len(name) > _MAX_NAME_LENGTH or _NAME_PATTERN.fullmatch(name) is None:
        errors.append("name must be 1-64 lowercase letters, digits, or single hyphens")
    if name != directory_name:
        errors.append(f"name '{name}' must match directory '{directory_name}'")
    return errors


def _validate_description(description: object) -> list[str]:
    if not isinstance(description, str) or not description.strip():
        return ["description must be a non-empty string"]
    if len(description.strip()) > _MAX_DESCRIPTION_LENGTH:
        return [f"description exceeds {_MAX_DESCRIPTION_LENGTH} characters"]
    return []


def _validate_skill(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return ["SKILL.md not found"]

    try:
        source = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [f"cannot read SKILL.md as UTF-8: {error}"]

    match = _FRONTMATTER_PATTERN.match(source)
    if match is None:
        return ["SKILL.md must start with YAML frontmatter"]

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        return [f"invalid YAML frontmatter: {error}"]
    if not isinstance(frontmatter, dict):
        return ["frontmatter must be a mapping"]

    unexpected = sorted(str(field) for field in set(frontmatter) - _ALLOWED_FIELDS)
    if unexpected:
        errors.append(f"unexpected frontmatter fields: {', '.join(unexpected)}")

    errors.extend(_validate_name(frontmatter.get("name"), skill_dir.name))
    errors.extend(_validate_description(frontmatter.get("description")))

    if not match.group(2).strip():
        errors.append("Markdown instructions must not be empty")
    if _TODO_PATTERN.search(source):
        errors.append("unresolved TODO placeholder found")
    return errors


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args()

    errors = _validate_skill(args.skill_dir.resolve())
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1
    print("[OK] Skill is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
