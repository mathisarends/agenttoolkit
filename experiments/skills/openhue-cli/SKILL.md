---
name: openhue-cli
description: Control Philips Hue lighting with the openhue CLI, especially room-first on/off control, absolute and relative brightness, scene discovery and activation, and read-only zone discovery. Use whenever the user asks to inspect or control Hue lights, rooms, zones, brightness, or scenes from the terminal.
---

# OpenHue CLI

`openhue` controls a paired Philips Hue Bridge. These instructions target CLI version 0.24.

## Control policy

- Prefer **rooms**, then **zones**; do not control individual lights unless the user explicitly asks for a specific light or accepts an individual-light fallback.
- Version 0.24 has first-class commands for rooms, lights, and scenes, but **no `get zone` or `set zone` command**. It can discover zone IDs only through the generic resource listing. Do not pretend that `set room` supports zones and do not expand a zone into individual-light writes automatically. Explain the limitation and ask for a room fallback when zone control is requested.
- Read-only discovery may be run without confirmation. Mutating commands (`set`) are consequential; execute them only when the user's request clearly asks for the change.
- Quote names containing spaces or shell metacharacters.

## Command groups

| Group | Purpose |
|---|---|
| `openhue get room` | List rooms or inspect room state |
| `openhue set room` | Switch or set brightness/color for up to 10 rooms |
| `openhue get scene` | List scenes, optionally filtered by room |
| `openhue set scene` | Activate static or dynamic scenes |
| `openhue get light` / `set light` | Individual-light fallback only |
| `openhue get --type zone` | Raw, read-only zone-ID discovery |
| `openhue setup` | Interactive bridge discovery and pairing |

Aliases `g`/`s`, `rooms`/`lights`/`scenes` exist, but use the canonical forms below for clarity.

## Prerequisite and discovery

Resource commands require prior pairing. If a read fails because setup/configuration is missing, run interactive setup only with the user's approval:

```bash
openhue setup
```

Never print or inspect `~/.openhue/config.yaml`; it contains the application key.

Discover real room and scene names before the first relevant mutation or when a name is ambiguous:

```bash
openhue get room
openhue get scene --room "<room-name-or-uuid>"
```

JSON is useful when state must be calculated:

```bash
openhue get room "<room-name-or-uuid>" --json
```

The room JSON exposes aggregate state at:

- `.GroupedLight.HueData.on.on`
- `.GroupedLight.HueData.dimming.brightness`
- scenes under `.Scenes[]`, including `.Name` and `.HueData.status.active`

A missing room can return JSON `null` with exit status 0, so test the JSON value rather than relying only on the exit code.

## Room-first control

Names and Hue v2 UUIDs are accepted as room selectors. Up to 10 selectors may be supplied to one mutation.

```bash
# On/off
openhue set room "<room>" --on
openhue set room "<room>" --off

# Multiple rooms
openhue set room "<room-1>" "<room-2>" --on

# Absolute brightness, 0..100 (decimals accepted)
openhue set room "<room>" --on --brightness <0-100>

# Smooth transition
openhue set room "<room>" --on --brightness <0-100> --transition-time <duration>
```

`<duration>` is a Go-style duration such as `500ms`, `5s`, or `1m`. The CLI requires `--on` when setting brightness, color, or temperature; brightness alone is not sufficient.

Verify after a mutation:

```bash
openhue get room "<room>" --json
```

### Relative brightness (brighter/darker)

There is no native relative-brightness flag. Read the room's aggregate brightness, add or subtract the requested percentage points, clamp to `0..100`, then write the result. Do not infer current brightness from a scene definition.

```bash
room='<room>'
delta='<signed-percentage-points>'   # e.g. 10 or -10
state="$(openhue get room "$room" --json)"
printf '%s' "$state" | jq -e '. != null and .GroupedLight.HueData.dimming.brightness != null' >/dev/null || exit 1
current="$(printf '%s' "$state" | jq -r '.GroupedLight.HueData.dimming.brightness')"
target="$(jq -nr --argjson current "$current" --argjson delta "$delta" '[$current + $delta, 0] | max | [., 100] | min')"
openhue set room "$room" --on --brightness "$target"
openhue get room "$room" --json
```

Interpret an unqualified “heller/dunkler” as a modest 10 percentage-point change. If the user says “um N Prozent”, treat N as percentage points unless they explicitly request multiplication relative to the current value.

## Scenes

List scenes in the target room first; this both verifies spelling and avoids ambiguity:

```bash
openhue get scene --room "<room-name-or-uuid>"
```

Activate a scene. Always include `--room` when the room is known because scene names may be duplicated:

```bash
openhue set scene "<scene-name-or-uuid>" --room "<room-name-or-uuid>"
```

The default action is `active`. Explicit modes are:

```bash
openhue set scene "<scene>" --room "<room>" --action static
openhue set scene "<scene>" --room "<room>" --action dynamic
```

Allowed actions are `active`, `static`, and `dynamic`. Not every scene necessarily supports a useful dynamic palette.

Verify activation by checking scene status (`active` is commonly `static`, `dynamic`, or `inactive`):

```bash
openhue get scene "<scene>" --room "<room>" --json
```

## Zones: version 0.24 limitation

Discover raw zone resources:

```bash
openhue get --type zone --json
```

This returns sparse Hue resources with `id`, `id_v1`, and `type`, but generally not usable names or aggregate state. Version 0.24 exposes neither `get zone` nor `set zone`; `set room <zone-id>` is undocumented and must not be used as if it were supported. For a zone request:

1. State that this installed CLI cannot safely control zones.
2. Offer room-level control.
3. Do not silently issue multiple `set light` commands.

## Individual-light fallback

Use only after an explicit individual-light request or explicit approval of the fallback:

```bash
openhue get light
openhue get light --room "<room>"
openhue set light "<light>" --room "<room>" --on
openhue set light "<light>" --room "<room>" --off
openhue set light "<light>" --room "<room>" --on --brightness <0-100>
openhue get light "<light>" --json
```

`set light` supports at most 10 lights per call. Use `--room` to disambiguate duplicate light names.

## Important failures and pitfalls

- `openhue --version` is invalid; use `openhue version`.
- Brightness range is `0..100`; validate and clamp computed values before mutation.
- Never combine `--on` and `--off`.
- Scene filtering and disambiguation use `--room`, not a zone option.
- Names beginning with `-` should be addressed by UUID to avoid flag parsing ambiguity.
- A successful process exit does not guarantee a resource was found; JSON reads may return `null`.
- Bridge/network/authentication errors should be reported without exposing the bridge application key or config file.
