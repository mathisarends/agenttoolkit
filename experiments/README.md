# Experiments

Run the chat entry points from the repository root:

```powershell
uv run python experiments\chat.py
uv run python experiments\chat_with_sandbox.py
uv run python experiments\chat_with_connected_sandbox.py
uv run python experiments\chat_with_bash_and_skills.py
```

The package is split by responsibility:

- `agent.py` contains the shared agent loop.
- `chat*.py` files are runnable compositions.
- `environments/` contains reusable user interfaces and runtimes.
- `sandboxing/` constructs isolated execution environments.
- `tools/` registers reusable agent tools.
- `skills/` contains only skill definitions and their resources.

Sandbox workspaces are created below the operating system's temporary directory,
not inside the source tree.
