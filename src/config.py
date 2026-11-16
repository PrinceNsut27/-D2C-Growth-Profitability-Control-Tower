"""Configuration loader, logging setup, and project constants."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.toml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.example.toml"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure structured console logging for the D2C Control Tower pipeline."""
    logger = logging.getLogger("d2c_control_tower")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def load_settings(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load TOML settings from config/settings.toml or fallback to settings.example.toml."""
    if config_path is not None:
        path = Path(config_path)
    elif DEFAULT_CONFIG_PATH.exists():
        path = DEFAULT_CONFIG_PATH
    else:
        path = EXAMPLE_CONFIG_PATH

    with open(path, "rb") as f:
        settings = tomllib.load(f)

    # Apply defaults for optional sections
    settings.setdefault("project", {})
    settings["project"].setdefault("name", "D2C Growth & Profitability Control Tower")
    settings["project"].setdefault("brand_name", "AuraVeda Skincare (Fictional Indian D2C Brand)")
    settings["project"].setdefault("currency", "INR")
    settings["project"].setdefault("timezone", "Asia/Kolkata")
    settings["project"].setdefault("synthetic_data", True)
    settings["project"].setdefault("random_seed", 42)
    settings["project"].setdefault("start_date", "2026-05-01")
    settings["project"].setdefault("end_date", "2026-10-31")

    settings.setdefault("generator", {})
    settings["generator"].setdefault("num_customers", 3200)
    settings["generator"].setdefault("num_orders", 6500)
    settings["generator"].setdefault("num_sessions", 48000)

    settings.setdefault("costs", {})
    settings["costs"].setdefault("prepaid_payment_fee_rate", 0.02)
    settings["costs"].setdefault("cod_payment_fee_fixed", 25.0)

    return settings
