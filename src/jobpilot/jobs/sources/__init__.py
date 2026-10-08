"""Job board adapters package."""

from jobpilot.jobs.sources.ashby import AshbyAdapter
from jobpilot.jobs.sources.base import (
    BaseJobBoardAdapter,
    FetchResult,
    JobBoardError,
    JobBoardNotFoundError,
    JobBoardRateLimitError,
)
from jobpilot.jobs.sources.greenhouse import GreenhouseAdapter
from jobpilot.jobs.sources.lever import LeverAdapter

_ADAPTERS: dict[str, BaseJobBoardAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "lever": LeverAdapter(),
    "ashby": AshbyAdapter(),
}


def get_adapter(ats: str) -> BaseJobBoardAdapter:
    """Return the adapter instance for the specified ATS."""
    ats_lower = ats.lower().strip()
    adapter = _ADAPTERS.get(ats_lower)
    if not adapter:
        raise ValueError(
            f"Unsupported ATS '{ats}'. Supported ATS platforms: {list(_ADAPTERS.keys())}"
        )
    return adapter


__all__ = [
    "AshbyAdapter",
    "BaseJobBoardAdapter",
    "FetchResult",
    "GreenhouseAdapter",
    "JobBoardError",
    "JobBoardNotFoundError",
    "JobBoardRateLimitError",
    "LeverAdapter",
    "get_adapter",
]
