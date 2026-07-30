---
name: hueify-cli
description: Control Philips Hue lights, rooms, and zones with the hueify CLI, including setup, resource discovery, state inspection, power, brightness, color temperature, and room or zone scenes. Use whenever the user asks to inspect or control Philips Hue from the terminal.
---

# Hueify CLI

`hueify` controls Philips Hue resources through these groups:

| Group    | Scope                  | Scenes |
| -------- | ---------------------- | ------ |
| `lights` | One named bulb         | No     |
| `rooms`  | All lights in one room | Yes    |
| `zones`  | All lights in one zone | Yes    |

## User preference: operate on rooms

Prefer controlling the entire room with `hueify rooms` instead of switching individual bulbs with `hueify lights`. Treat the room as one coherent lighting unit for power, brightness, temperature, and scenes. Use an individual light only when the user explicitly names or requests a single bulb, or when the requested operation cannot be performed at room level. Prefer a zone only when the user explicitly refers to that zone or its scope is clearly intended.

## Authentication and setup

Normally use the saved configuration. If onboarding is explicitly requested, run the interactive workflow below; it discovers a bridge, requires physical confirmation on the bridge, registers an application key, and saves configuration:

```bash
hueify setup
```

For one invocation, global `--bridge-ip <IPv4-or-host>` and `--app-key <key>` override `HUE_BRIDGE_IP` / `HUE_APP_KEY` and saved configuration. Put global flags before the command group. Never print or expose an application key.

## Discover names first

Before reading or changing a resource, obtain its exact name from the matching group:

```bash
hueify lights list
hueify rooms list
hueify zones list
```

Names are string positional arguments and are resource-type-specific. Quote every name or scene containing spaces or shell metacharacters, for example `"Living Room"`.

## Read state

For any `<group>` equal to `lights`, `rooms`, or `zones`:

```bash
hueify <group> info <name>
hueify <group> brightness-get <name>
```

`info` shows power and brightness. Room and zone information also shows the active scene and available scenes. `brightness-get` prints the brightness percentage directly. Group brightness is the Hue grouped-light value, not a per-bulb breakdown.

Room and zone scene reads:

```bash
hueify rooms scenes <room-name>
hueify rooms active-scene <room-name>
hueify zones scenes <zone-name>
hueify zones active-scene <zone-name>
```

`active-scene` may successfully report that no scene is active.

## Change state

The common command shape is identical for lights, rooms, and zones:

```bash
hueify <group> on <name>
hueify <group> off <name>
hueify <group> brightness <name> <0-100>
hueify <group> brightness-up <name> <0-100>
hueify <group> brightness-down <name> <0-100>
hueify <group> temperature <name> <0-100>
```

Values are floating-point percentages. `brightness` is absolute; `brightness-up` and `brightness-down` are relative. Hueify clamps values outside `0-100`, reports the clamp, and can still exit successfully. Brightness readback may differ slightly because Hue hardware/API values are quantized.

Temperature is a normalized device-relative percentage: `0` is warmest and `100` coolest. A light that does not support color temperature can reject the operation.

Scenes exist only for rooms and zones. Discover valid scene names before activation:

```bash
hueify rooms scenes <room-name>
hueify rooms activate-scene <room-name> <scene-name>
hueify zones scenes <zone-name>
hueify zones activate-scene <zone-name> <scene-name>
```

Quote room, zone, and scene names independently when needed:

```bash
hueify rooms activate-scene "Living Room" "Warm Sunset"
```

## Verify mutations

After power, brightness, or temperature changes, inspect the target:

```bash
hueify <group> info <name>
```

For a precise brightness check:

```bash
hueify <group> brightness-get <name>
```

After scene activation:

```bash
hueify rooms active-scene <room-name>
hueify zones active-scene <zone-name>
```

## Failures and safety

- Successful reads and tested mutations exit `0`; missing resources exit nonzero and print `Not found`, often with suggestions.
- Syntax and unknown-option errors exit nonzero and print usage. There is no `--version` option in hueify 0.6.1.
- Discovery and read commands are safe. Power, brightness, temperature, scene activation, and `setup` have external effects; execute them only when the user requests the change.
- Do not infer that a light name is also a room or zone name. Use the matching `list` command.
