#!/usr/bin/env python
"""Django's command-line utility for StudyCrew."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - only reached before setup
        raise ImportError(
            "Django is not installed. Create the virtual environment and install "
            "requirements/dev.txt before running this command."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
