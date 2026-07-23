#!/usr/bin/env python
import os
import sys


def main() -> None:
    settings_module = (
        "config.settings.test"
        if len(sys.argv) > 1 and sys.argv[1] == "test"
        else "config.settings.development"
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is unavailable. Install the project dependencies first."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
