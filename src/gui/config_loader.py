"""GUI Configuration Loader for GNLSE Desktop Workstation.

Handles loading formatting preferences from `config.json` (such as window
geometry, default domain view, splitter proportions, colormap defaults, and
theme colors). Provides robust fallback to sane defaults if `config.json`
is missing, corrupted, or invalid.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)

# Standard default configuration
DEFAULT_CONFIG: Dict[str, Any] = {
    "window": {
        "title": "GNLSE Pulse Propagation Simulator — High Performance Laboratory",
        "width": 1440,
        "height": 940,
    },
    "results_view": {
        "default_domain": "FREQUENCY DOMAIN",  # 'FREQUENCY DOMAIN' or 'TIME DOMAIN'
        "default_colormap": "turbo",
        "default_db_floor": -40.0,
        "time_range_ps": [-2.5, 2.5],
        "wl_range_nm": [500.0, 1200.0],
        "v_splitter_sizes": [950, 50],
        "diagnostics_minimized": True,
    },
    "theme": {
        "bg_dark": "#0f131d",
        "surface_lowest": "#0a0e18",
        "surface_low": "#171b26",
        "surface": "#1c1f2a",
        "surface_high": "#262a35",
        "surface_highest": "#313540",
        "surface_bright": "#353944",
        "cyan_accent": "#00f5ff",
        "cyan_bright": "#63f7ff",
        "cyan_light": "#e9feff",
        "cyan_dark": "#003739",
        "pink_accent": "#ff4b89",
        "pink_light": "#ffb1c3",
        "pink_dark": "#3f0019",
        "purple_accent": "#703eda",
        "purple_light": "#e5d7ff",
        "purple_dark": "#23005c",
        "text_primary": "#dfe2f1",
        "text_muted": "#b9caca",
        "border_color": "#3a494a",
        "border_subtle": "#262a35",
        "green_success": "#00e676",
        "amber_warning": "#ffab00",
        "red_error": "#ff5252",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override dictionary into base dictionary without mutating base."""
    merged: Dict[str, Any] = {}
    for key, val in base.items():
        if key in override:
            if isinstance(val, dict) and isinstance(override[key], dict):
                merged[key] = _deep_merge(val, override[key])
            else:
                merged[key] = override[key]
        else:
            merged[key] = val
    for key, val in override.items():
        if key not in merged:
            merged[key] = val
    return merged


def get_default_config_path() -> Path:
    """Return the candidate Path for config.json (prefers repository root)."""
    env_path = os.environ.get("GNLSE_CONFIG_PATH")
    if env_path:
        return Path(env_path)

    # Repository root: 3 levels up from src/gui/config_loader.py
    repo_root = Path(__file__).resolve().parent.parent.parent
    root_config = repo_root / "config.json"
    if root_config.exists():
        return root_config

    gui_config = Path(__file__).resolve().parent / "config.json"
    if gui_config.exists():
        return gui_config

    return root_config


def load_gui_config(config_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load configuration dictionary from config.json with graceful fallback.

    If the file is not found, corrupt, or has missing keys, it returns a valid
    dictionary populated with default values.
    """
    path = Path(config_path) if config_path else get_default_config_path()

    if not path.is_file():
        return json.loads(json.dumps(DEFAULT_CONFIG))

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        if not isinstance(raw_data, dict):
            logger.warning("Configuration in %s is not a dictionary. Falling back to defaults.", path)
            return json.loads(json.dumps(DEFAULT_CONFIG))
        return _deep_merge(DEFAULT_CONFIG, raw_data)
    except Exception as exc:
        logger.warning("Failed to load configuration from %s (%s). Using defaults.", path, exc)
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_gui_config(config_dict: Dict[str, Any], config_path: Optional[Union[str, Path]] = None) -> Path:
    """Save configuration dictionary to a formatted JSON file."""
    path = Path(config_path) if config_path else get_default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2)
    return path
