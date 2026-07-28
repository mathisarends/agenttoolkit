import asyncio
import tempfile
from pathlib import Path

from agenttoolkit import Skills

SKILL_MD = """\
---
name: greeting
description: Greet a user by name in a friendly tone.
---

# Greeting

Read `template.txt` for the exact phrasing to use, then fill in the name.
"""


def _make_skills_dir(root: Path) -> Path:
    skill_dir = root / "greeting"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (skill_dir / "template.txt").write_text("Hey {name}, welcome!", encoding="utf-8")
    return root


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        skills_root = _make_skills_dir(Path(tmp))
        skills = Skills.from_local_dir(skills_root)

        # A short catalog an agent can see up front, before deciding to load
        # any particular skill's full instructions.
        print(skills.catalog())

        # Full instructions plus a manifest of the skill's own resource files.
        print(skills.load("greeting"))

        # Resources are read on demand and scoped to the skill's directory.
        print(skills.read_resource("greeting", "template.txt"))


if __name__ == "__main__":
    asyncio.run(main())
