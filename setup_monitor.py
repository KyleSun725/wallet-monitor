"""Prepare a private Python environment for wallet-monitor.

Run this file with the Python installed on your computer:

    python setup_monitor.py

The script creates ".venv", installs the dependencies, and optionally writes
the BUZZ API key to the ignored local ".env" file. It never prints the key.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"
ENV_FILE = PROJECT_DIR / ".env"
ENV_EXAMPLE = PROJECT_DIR / ".env.example"


def venv_python() -> Path:
    """Return the interpreter inside the local virtual environment."""

    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def install_dependencies() -> None:
    """Create the virtual environment and install pinned dependencies."""

    if not venv_python().exists():
        print("Creating .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    python = str(venv_python())
    print("Installing dependencies ...")
    subprocess.run(
        [python, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)],
        cwd=PROJECT_DIR,
        check=True,
    )


def create_local_config() -> None:
    """Create .env without overwriting an existing private configuration."""

    if ENV_FILE.exists():
        print("Keeping the existing .env file.")
        return

    print()
    print("Paste your BUZZ API key below. Input is hidden for safety.")
    print("Press Enter to skip and edit .env later.")
    api_key = getpass.getpass("BUZZ API key: ").strip()
    if "\n" in api_key or "\r" in api_key:
        raise ValueError("The API key must be a single line.")

    if api_key:
        ENV_FILE.write_text(
            "# Private local configuration. Do not commit this file.\n"
            f"BUZZ_API_KEY={api_key}\n"
            "BUZZ_BASE_URL=https://buzzai.cc\n"
            "BUZZ_REFRESH_SECONDS=300\n"
            "BUZZ_CURRENCY_SYMBOL=$\n",
            encoding="utf-8",
        )
        print("Saved the key to the ignored local .env file.")
    else:
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        print("Created .env from the safe example; replace its placeholder before starting.")


def main() -> int:
    if sys.version_info < (3, 8):
        print("Python 3.8 or newer is required.", file=sys.stderr)
        return 1
    if os.name != "nt":
        print("wallet-monitor currently supports Windows 10 and Windows 11 only.", file=sys.stderr)
        return 1

    try:
        install_dependencies()
        create_local_config()
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1

    print()
    print("Setup complete. Start the widget with:")
    print("    python run_monitor.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())