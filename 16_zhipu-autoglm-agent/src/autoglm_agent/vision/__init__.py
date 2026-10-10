from __future__ import annotations

from .base import NullTemplate, OcrBackend, OcrHit, TemplateBackend, TemplateHit  # noqa: F401
from .ocr import NullOcr, OcrConsensus, RapidOcr, VirtualJsonOcr, default_ocr  # noqa: F401
from .template import (CvTemplateBackend, ExampleTemplateBackend,  # noqa: F401
                       default_templates, known_templates)

__all__ = ["OcrBackend", "OcrHit", "TemplateBackend", "TemplateHit", "NullTemplate",
           "NullOcr", "VirtualJsonOcr", "RapidOcr", "OcrConsensus", "default_ocr",
           "ExampleTemplateBackend", "CvTemplateBackend", "default_templates",
           "known_templates"]
