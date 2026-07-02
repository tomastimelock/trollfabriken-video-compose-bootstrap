"""
VideoComposeConfig — loads ~/.video_compose/config.toml.

Resolution order (later overrides earlier):
  1. Built-in defaults
  2. Config file (~/.video_compose/config.toml or explicit path)
  3. Environment variables (VIDEO_COMPOSE_*)
  4. Per-call keyword arguments (applied by callers)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG_PATH = Path.home() / ".video_compose" / "config.toml"

_ENV_PREFIX = "VIDEO_COMPOSE_"

_DEFAULTS: dict[str, Any] = {
    "min_confidence": 0.6,
    "template_dir": str(Path.home() / ".video_compose" / "templates"),
    "llm_model": "gpt-4.1",
    "llm_provider": "openai",
}


@dataclass
class VideoComposeConfig:
    min_confidence: float = 0.6
    template_dir: Path = field(default_factory=lambda: Path.home() / ".video_compose" / "templates")
    llm_model: str = "gpt-4.1"
    llm_provider: str = "openai"

    def with_overrides(self, **kwargs: Any) -> "VideoComposeConfig":
        """Return a new config with the given keyword overrides applied."""
        import dataclasses
        current = dataclasses.asdict(self)
        current.update({k: v for k, v in kwargs.items() if v is not None})
        if "template_dir" in current and not isinstance(current["template_dir"], Path):
            current["template_dir"] = Path(current["template_dir"])
        return VideoComposeConfig(**current)


def load_config(config_path: Path | None = None) -> VideoComposeConfig:
    """Load config from file + environment, returning a VideoComposeConfig.

    Args:
        config_path: Explicit path to a .toml config file. Defaults to
                     ~/.video_compose/config.toml if it exists.
    """
    data: dict[str, Any] = dict(_DEFAULTS)

    # File
    path = config_path or _DEFAULT_CONFIG_PATH
    if path.exists():
        data.update(_load_toml(path))

    # Environment
    for key in ("min_confidence", "template_dir", "llm_model", "llm_provider"):
        env_key = _ENV_PREFIX + key.upper()
        env_val = os.environ.get(env_key)
        if env_val is not None:
            data[key] = env_val

    return VideoComposeConfig(
        min_confidence=float(data.get("min_confidence", 0.6)),
        template_dir=Path(str(data.get("template_dir", _DEFAULTS["template_dir"]))),
        llm_model=str(data.get("llm_model", "gpt-4.1")),
        llm_provider=str(data.get("llm_provider", "openai")),
    )


def save_config(config: VideoComposeConfig, config_path: Path | None = None) -> None:
    """Save *config* to a TOML file."""
    path = config_path or _DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'min_confidence = {config.min_confidence}',
        f'template_dir = "{config.template_dir}"',
        f'llm_model = "{config.llm_model}"',
        f'llm_provider = "{config.llm_provider}"',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# TOML loading — tomllib (stdlib 3.11+) with fallback error
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict[str, Any]:
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            return tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            try:
                import tomli
                return tomli.loads(path.read_text(encoding="utf-8"))
            except ImportError:
                import warnings
                warnings.warn(
                    f"Cannot load {path}: install 'tomli' for TOML support on Python <3.11",
                    stacklevel=3,
                )
                return {}
    except Exception as exc:
        import warnings
        warnings.warn(f"Failed to load config from {path}: {exc}", stacklevel=3)
        return {}
