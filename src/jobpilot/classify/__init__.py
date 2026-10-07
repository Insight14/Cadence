"""Classification package initialization."""

from jobpilot.classify.llm_classifier import LLMClassifier
from jobpilot.classify.rules import is_candidate_email
from jobpilot.classify.schemas import ClassificationResult, EmailLabel

__all__ = [
    "ClassificationResult",
    "EmailLabel",
    "LLMClassifier",
    "is_candidate_email",
]
