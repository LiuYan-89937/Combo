from __future__ import annotations

import os


def allowed_frontend_origins() -> tuple[str, ...]:
    configured = os.getenv("COMBO_FRONTEND_ORIGINS")
    if configured is not None:
        return tuple(origin.strip() for origin in configured.split(",") if origin.strip())
    return (
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    )
