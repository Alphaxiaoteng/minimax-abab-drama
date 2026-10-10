from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on") if name in os.environ else default


@dataclass
class Settings:
    api_key: str = field(default_factory=lambda: os.environ.get("ZHIPU_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"))
    model: str = field(default_factory=lambda: os.environ.get("AUTOGLM_MODEL", "autoglm"))
    vision_model: str = field(default_factory=lambda: os.environ.get("GLM_VISION_MODEL", "glm-4v-air"))
    request_timeout: float = float(os.environ.get("ZHIPU_TIMEOUT", "60"))
    allow_offline_planner: bool = _env_bool("AUTOGLM_ALLOW_OFFLINE", True)

    max_step_retries: int = int(os.environ.get("FLOW_MAX_RETRIES", "3"))
    retry_backoff_base: float = float(os.environ.get("FLOW_BACKOFF_BASE", "0.6"))
    locate_timeout: float = float(os.environ.get("LOCATE_TIMEOUT", "12"))
    locate_poll_interval: float = float(os.environ.get("LOCATE_POLL", "0.8"))
    max_scroll_probe: int = int(os.environ.get("LOCATE_MAX_SCROLL", "6"))
    scroll_settle: float = float(os.environ.get("LOCATE_SCROLL_SETTLE", "0.35"))
    action_max_verify: int = int(os.environ.get("ACTION_MAX_VERIFY", "2"))
    blank_settle: float = float(os.environ.get("BLANK_SETTLE", "0.4"))

    checkpoint_dir: str = os.environ.get("CHECKPOINT_DIR", ".autoglm_runtime/checkpoints")
    artifact_dir: str = os.environ.get("ARTIFACT_DIR", ".autoglm_runtime/artifacts")

    @property
    def api_enabled(self) -> bool:
        return bool(self.api_key)


def load_settings() -> Settings:
    return Settings()
