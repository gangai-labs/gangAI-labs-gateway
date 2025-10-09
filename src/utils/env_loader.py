# file: src/utils/env_loader.py
# Copyright (c) 2025 gangAI-labs. All rights reserved.
# This file is part of a demonstration project. See LICENSE for usage terms.
"""
Dotenv Wrapper: Robust env var loading with auto-trim for inline comments (#) and safe casting.
Design: Wraps python-decouple for centralized .env handling. Load once (load_env()), then get_env() everywhere.
Handles: "True # dev note" → True (bool). Defaults prevent crashes. For gangAI-labs demo: Minimal, no new deps.
Usage: In app.py: load_env(); In config.py: get_env(key, default, cast=bool).
"""


from typing import Union, Optional, Any
from dotenv import load_dotenv  # pip install python-dotenv (already in your deps)
from decouple import AutoConfig, UndefinedValueError  # Your existing decouple

# Global config instance (loaded once)
_config = None


def load_env(env_path: str = ".env") -> None:
    """
    Load .env file once (call in app.py [3] early).
    Args:
        env_path: Path to .env (default: ".env" in project root).
    Raises:
        FileNotFoundError: If .env missing (uses defaults).
    """
    global _config
    if _config is not None:
        pass

    try:
        # Load .env via dotenv (raw os.environ)
        load_dotenv(env_path)
        # Wrap with decouple for safe access (with our custom trim/cast)
        _config = AutoConfig()  # Auto-detects .env
        #print("Env loaded successfully from", env_path)  # Demo log
    except FileNotFoundError:
        print(f"Warning: {env_path} not found—using defaults.")
        _config = AutoConfig()  # Fallback to os.environ/defaults


def get_env(key: str, default: Optional[Any] = None, cast: Optional[Union[type, str]] = None) -> Any:
    """
    Get env var with auto-trim (# comments) and safe cast.
    Args:
        key: Env var name (e.g., "RELOAD").
        default: Fallback value if missing (str, int, bool, etc.).
        cast: Type to cast (bool, int, float, str; None = str).
    Returns:
        Value (casted if possible).
    Raises:
        ValueError: If cast fails (e.g., "abc" to int) with helpful msg.
    Example:
        get_env("RELOAD", default="True", cast=bool)  # "True # note" → True
        get_env("PORT", default="8000", cast=int)  # "8000 # dev" → 8000
    """
    if _config is None:
        raise ValueError("Call load_env() first (e.g., in app.py [3]).")

    try:
        # Get raw value
        raw_value = _config(key, default=str(default) if default is not None else None)
        if raw_value is None:
            return default

        # Auto-trim inline comments (#) and whitespace
        trimmed = raw_value.split('#')[0].strip()

        if cast is None:
            return trimmed  # Str

        # Safe casting
        if cast == bool:
            lower_trim = trimmed.lower().strip()
            if lower_trim in ('true', '1', 'yes', 'on', 't', 'y'):
                return True
            elif lower_trim in ('false', '0', 'no', 'off', 'f', 'n'):
                return False
            else:
                raise ValueError(f"Invalid bool value for {key}: '{trimmed}' (expected true/false-like)")

        elif cast == int:
            return int(trimmed)

        elif cast == float:
            return float(trimmed)

        else:
            raise ValueError(f"Unsupported cast '{cast}' for {key} (use bool/int/float/None)")

    except UndefinedValueError:
        return default
    except Exception as e:
        raise ValueError(f"Failed to load/cast {key}: {e}")


# Export for easy import (e.g., from config import get_env)
__all__ = ["load_env", "get_env"]
