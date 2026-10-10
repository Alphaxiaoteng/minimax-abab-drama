from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .screen import Screen, capture, normalize_text  # noqa: F401

__all__ = ["Screen", "capture", "normalize_text"]
