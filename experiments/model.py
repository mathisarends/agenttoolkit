from __future__ import annotations

import httpx
from llmify import ChatCodex, RetryCallback

# llmify caps its exponential backoff at 8s per retry, so a high retry count is
# what buys wall-clock patience: ~40s of waiting inside a single invoke, which
# covers the short "servers are overloaded" windows the Codex backend produces.
MAX_RETRIES = 8

# A streaming response can idle between events while the model reasons; the
# read timeout has to outlast that, while connect/pool stay short so a dead
# connection fails fast into a retry instead of hanging the REPL.
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=10.0)


def experiment_model(model: str, *, on_retry: RetryCallback | None = None) -> ChatCodex:
    return ChatCodex.from_cli(
        model=model,
        timeout=TIMEOUT,
        max_retries=MAX_RETRIES,
        on_retry=on_retry,
    )
