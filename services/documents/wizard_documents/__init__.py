"""Turn Office files, Outlook mail and attachments into text Gemini can read (pywin32 + Office on Windows, the standard
library elsewhere): attached files, the files a task reads, how presentations look, edited workbook copies and the
Email button's Outlook draft. Wizard runs these in a process of its own (cli.py); kb.py writes to the knowledge-base
repository."""
from __future__ import annotations

from .common import ConversionError, Converted, kind_of
from .convert import Converter, convert

__all__ = ["ConversionError", "Converted", "Converter", "convert", "kind_of"]
