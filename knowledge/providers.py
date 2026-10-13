"""The domain adapter keeps all outbound HTTP inside integrations."""
from integrations.rag_model import ProviderUnavailable, configuration, generate

__all__ = ["ProviderUnavailable", "configuration", "generate"]
