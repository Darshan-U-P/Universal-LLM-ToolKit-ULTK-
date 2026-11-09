"""Provider adapter interfaces and test doubles."""

from ultk.providers.base import ProviderAdapter
from ultk.providers.mock import MockProvider

__all__ = ["MockProvider", "ProviderAdapter"]
