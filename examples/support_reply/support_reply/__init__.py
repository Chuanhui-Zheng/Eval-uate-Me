"""Support reply example plugin for evalharness — open-ended generation with LLM judge."""

from .agent import SupportReplyTarget
from .llm_agent import LLMReplyTarget

__all__ = ["SupportReplyTarget", "LLMReplyTarget"]
