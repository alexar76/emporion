"""SYMMARTYS configuration, including explicit state-preserving upgrade behavior.

The product/capability namespace changed at 0.5.0. Persisted keys did not: an
existing installation must continue signing with its existing identity.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("symmartys.config")


def setting(suffix: str, default: str = "") -> str:
    """Read SYMMARTYS_* first; warn when using a legacy EMPORION_* setting."""
    current, legacy = f"SYMMARTYS_{suffix}", f"EMPORION_{suffix}"
    if current in os.environ:
        return os.environ[current]
    if legacy in os.environ:
        log.warning("Using legacy configuration %s; migrate it to %s", legacy, current)
        return os.environ[legacy]
    return default


def signing_key_path() -> Path:
    """Keep the existing key, or require an explicit choice if two identities exist."""
    for prefix in ("SYMMARTYS", "EMPORION"):
        name = f"{prefix}_SIGNING_KEY_PATH"
        if name in os.environ:
            configured = setting("SIGNING_KEY_PATH")
            if not configured.strip():
                raise ValueError(f"{name} must name a signing key file")
            return Path(configured)
    state = Path(setting("STATE_DIR", "data"))
    current, legacy = state / "symmartys_signing_key", state / "emporion_signing_key"
    if current.exists() and legacy.exists():
        raise ValueError("Both current and legacy signing keys exist; set "
                         "SYMMARTYS_SIGNING_KEY_PATH explicitly to preserve the intended identity")
    if legacy.exists():
        log.warning("Reusing the existing legacy signing key; set SYMMARTYS_SIGNING_KEY_PATH "
                    "explicitly before moving or rotating identity files")
        return legacy
    return current


__all__ = ["setting", "signing_key_path"]
