"""Read-only source adapters and the tool catalog Gemini can call.

Every tool here is read-only and bounded. A tool checks the caller's rights, the allowed operation, row/time bounds and
parameters; it never chooses the analysis on Gemini's behalf. Source responses are untrusted data."""
