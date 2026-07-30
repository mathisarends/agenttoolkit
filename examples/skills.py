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


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        skills_root = _make_skills_dir(Path(tmp))
        skills = Skills.from_local_dir(skills_root)

        # A short catalog an agent can see up front, before deciding to load
        # any particular skill's full instructions.
        print(skills.render_prompt())

        # Full instructions plus paths to resources that can be read or executed
        # through the application's general filesystem and process tools.
        loaded = skills.load("greeting")
        print(loaded.instructions)
        print(loaded.resources)

        # This direct read stands in for the application's general filesystem tool.
        template_path = loaded.directory / loaded.resources[0]
        print(template_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
