# Placeholder — implemented in task #29
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DataFetcher(ABC):
    """Base class for all data source adapters."""

    @abstractmethod
    def fetch(self, config: dict) -> Any:
        """Fetch data from source. Returns DataFrame, dict, or list."""
