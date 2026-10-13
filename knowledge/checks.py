from django.core.checks import Error, register
from .providers import configuration, ProviderUnavailable


@register()
def model_configuration(app_configs, **kwargs):
    try:
        configuration()
    except ProviderUnavailable:
        return [Error("Invalid RAG configuration. Use disabled, or configure ollama/compatible with a model, "
                      "an HTTPS or loopback base URL, and a 1–20 second timeout.", id="knowledge.E001")]
    return []
