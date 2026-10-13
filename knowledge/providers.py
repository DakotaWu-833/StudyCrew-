"""The domain adapter keeps all outbound HTTP inside integrations."""
from integrations.rag_model import ProviderUnavailable, configuration, generate
from integrations.rag_agent import agent_chat

__all__ = ["ProviderUnavailable", "configuration", "generate", "agent_chat"]
