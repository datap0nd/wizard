"""Turn Office files, Outlook mail and attachments into text Gemini can read (pywin32 + Office on Windows, the standard
library elsewhere), and the deterministic helpers of the Gemini CLI documentation kit."""
from __future__ import annotations

from .common import ConversionError, Converted, kind_of
from .convert import Converter, convert

__all__ = ["ConversionError", "Converted", "Converter", "convert", "kind_of"]
