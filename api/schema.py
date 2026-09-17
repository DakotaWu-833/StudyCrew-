"""OpenAPI extensions for StudyCrew's cookie-based MFA session."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class MFASessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "api.authentication.MFASessionAuthentication"
    name = "mfaSession"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sessionid",
            "description": (
                "Authenticated Django session created only after password and email OTP. "
                "Unsafe requests also require the csrftoken cookie value in X-CSRFToken."
            ),
        }
