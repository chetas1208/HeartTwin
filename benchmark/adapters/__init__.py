"""Adapters that map a benchmark case to a common output schema.

Both the HeartTwin system and a baseline LLM implement the SAME interface
(`infer(case) -> AdapterOutput`) so one grader can score them head-to-head.
"""

from .common import AdapterOutput, Measurement  # noqa: F401
