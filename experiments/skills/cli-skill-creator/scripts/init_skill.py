#!/usr/bin/env python3
"""Create a minimal skill folder."""

import argparse
import re
import sys
from pathlib import Path

_MAX_NAME_LENGTH = 64
_RESOURCE_DIRECTORIES = ("scripts", "references", "assets")

_SKILL_TEMPLATE = """---
name: {name}
description: "TODO: Say what the skill does and when it should be used."
---

# {title}

1. TODO: Inspect the relevant input.
2. TODO: Perform the workflow.
3. TODO: Validate the observable result.
"""


def _normalize_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-")


def _parse_resources(value: str) -> list[str]:
    resources = list(
        dict.fromkeys(part.strip() for part in value.split(",") if part.strip())
    )
    invalid = sorted(set(resources) - set(_RESOURCE_DIRECTORIES))
    if invalid:
        raise ValueError(
            f"unknown resource type(s): {', '.join(invalid)}; "
            f"choose from {', '.join(_RESOURCE_DIRECTORIES)}"
        )
    return resources


def _create_skill(name: str, root: Path, resources: list[str]) -> Path:
    target = root.expanduser().resolve() / name
    if target.exists():
        raise FileExistsError(f"skill directory already exists: {target}")

    target.mkdir(parents=True)
    title = " ".join(part.capitalize() for part in name.split("-"))
    (target / "SKILL.md").write_text(
        _SKILL_TEMPLATE.format(name=name, title=title),
        encoding="utf-8",
    )
    for resource in resources:
        (target / resource).mkdir()
    return target


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Skill name; normalized to lowercase hyphen-case")
    parser.add_argument("--path", required=True, type=Path, help="Writable skills root")
    parser.add_argument(
        "--resources",
        default="",
        help="Comma-separated subset of scripts,references,assets",
    )
    args = parser.parse_args()

    name = _normalize_name(args.name)
    if not name:
        parser.error("name must contain a letter or digit")
    if len(name) > _MAX_NAME_LENGTH:
        parser.error(f"normalized name exceeds {_MAX_NAME_LENGTH} characters")

    try:
        resources = _parse_resources(args.resources)
        target = _create_skill(name, args.path, resources)
    except (FileExistsError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    print(f"[OK] Created {target}")
    print("Edit SKILL.md, remove every TODO, then run quick_validate.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
