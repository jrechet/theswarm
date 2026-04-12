"""Entry point: python -m theswarm [command]

Delegates to the v2 Clean Architecture CLI.
Legacy flags (--cycle, --dev-only, --techlead-only) are translated to v2 commands.
No arguments starts the server (equivalent to 'serve').
"""

from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]

    # Translate legacy flags to v2 CLI commands
    if "--cycle" in args:
        from theswarm.presentation.cli.main import main as cli_main
        cli_main(["run-cycle"])
        return

    if "--dev-only" in args:
        from theswarm.presentation.cli.main import main as cli_main
        cli_main(["run-cycle", "--dev-only"])
        return

    if "--techlead-only" in args:
        from theswarm.presentation.cli.main import main as cli_main
        cli_main(["run-cycle", "--techlead-only"])
        return

    # All other commands (including no args → serve) go through v2 CLI
    from theswarm.presentation.cli.main import main as cli_main

    if not args:
        cli_main(["serve"])
    else:
        cli_main(args)


if __name__ == "__main__":
    main()
