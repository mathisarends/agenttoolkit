---
name: cli-skill-creator
description: Create or update a compact Codex skill for any CLI by documenting its namespaces, exact command syntax, common operations, required parameters, output and error behavior, and CLI-specific pitfalls. Use when an agent should be able to perform frequent CLI tasks directly from the generated skill without repeatedly invoking --help.
---

# Create a CLI Skill

Build a skill that lets an agent perform common operations without consulting `--help`. Use help and local documentation while creating the skill, but record the resulting exact commands in the generated `SKILL.md`.

## Explore the CLI

1. Identify the executable, version, global options, authentication, and available local documentation.
2. Use `--help` to map top-level namespaces or command groups and summarize their purpose in a small table.
3. For each relevant namespace, determine:
   - exact command shape and argument order
   - required parameters, defaults, and global options
   - which flags are required, which materially change behavior, and which are merely optional conveniences
   - resource types that always require additional arguments
   - accepted ranges, formats, and quoting rules
   - output modes, exit codes, and error behavior
   - safe read operations to run before mutations
4. Do not run destructive or externally consequential test commands without explicit authorization.

## Name the Target Skill

Derive the name directly from the CLI executable so generated skills remain consistent:

- folder and frontmatter `name`: `<cli>-cli` in lowercase hyphen-case
- document title: `<CLI> CLI`, preserving the CLI's normal capitalization
- frontmatter `description`: state what the CLI controls or manages and list the concrete task categories that should trigger the skill

Do not invent a broader product or workflow name. For example:

```yaml
---
name: spogo-cli
description: Control Spotify playback with the spogo CLI, including status, play and pause, track navigation, volume, shuffle, repeat, seeking, search, queues, devices, and playlists. Use whenever the user asks to inspect or control Spotify from the terminal.
---

# Spogo CLI
```

## Write the Target Skill

Keep `SKILL.md` concise and operational. Include:

- precise frontmatter describing the CLI tasks that trigger the skill
- a namespace overview
- any discovery required before the first action
- exact commands for the most frequent read and write operations
- placeholders such as `<name>` or `<id>` with their required formats
- mandatory parameter combinations and resource-specific exceptions
- verification commands for mutations
- important output, clamping, rate-limit, and failure behavior

An agent reading the target skill should not need `--help` for frequent operations. Do not merely name commands: include copyable command forms with all required positional arguments and options.

Prefer the shortest command that correctly performs the operation. Include a flag only when it is required, prevents ambiguity, improves safety, or provides an output format the workflow actually consumes. Do not add flags such as `--json`, `--no-color`, verbosity controls, or field filters by default; document them only when their benefit is concrete.

Do not add intent maps that translate obvious natural-language requests into commands. Assume the agent can map “pause,” “next,” or “set volume to 35” to clearly named operations. Use examples only to explain non-obvious syntax, ambiguous concepts, mandatory combinations, or surprising behavior.

Keep uncommon or extensive namespaces in `references/<namespace>.md` and link each file directly from `SKILL.md`. Always retain the most frequent operations in the main skill.

## Iterative Self-Improvement

Test several representative paths using explicit assumptions about how the CLI works: discovery, reading state, mutation or creation, and error handling. Start with help and read operations. Use mutations only in a safe test environment or when explicitly authorized.

Compare observed syntax, output, and errors with the assumptions. Remove redundant intent examples and optional flags that proved unnecessary. Update the generated skill whenever a required step, parameter, exception, or verification path is missing. Re-run the affected path until its common operation can be completed from the skill alone, then validate the skill with:

```bash
scripts/quick_validate.py <skill-directory>
```

## Short Example: Hueify

````markdown
`hueify` controls Philips Hue resources through three command groups:

| Group | Controls | Has scenes |
|---|---|---|
| `hueify lights` | a single bulb | no |
| `hueify rooms` | all bulbs in a room | yes |
| `hueify zones` | all bulbs in a zone | yes |

Discover the real resource names before acting:

```bash
hueify lights list
hueify rooms list
hueify zones list
```

Common commands exist for `lights`, `rooms`, and `zones`:

```bash
hueify <group> info <name>
hueify <group> on <name>
hueify <group> off <name>
hueify <group> brightness <name> <0-100>
hueify <group> brightness-up <name> <0-100>
hueify <group> brightness-down <name> <0-100>
hueify <group> brightness-get <name>
hueify <group> temperature <name> <0-100>
```

Scenes exist only for rooms and zones:

```bash
hueify rooms scenes <name>
hueify rooms active-scene <name>
hueify rooms activate-scene <name> <scene>
```

Quote names containing spaces:

```bash
hueify rooms brightness "Living Room" 40
```
