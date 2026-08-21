"""Start wallet-monitor with the interpreter prepared by setup_monitor.py.

Normal use:

    python run_monitor.py

For troubleshooting, keep the application attached to the terminal:

    python run_monitor.py --foreground
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
ENV_FILE = PROJECT_DIR / ".env"
APP_FILE = PROJECT_DIR / "wallet_monitor.py"
PLACEHOLDER = "replace-with-your-key"


def environment_python(windowed: bool) -> Path:
    if os.name == "nt":
        name = "pythonw.exe" if windowed else "python.exe"
        return VENV_DIR / "Scripts" / name
    return VENV_DIR / "bin" / "python"


def configured() -> bool:
    if not ENV_FILE.exists():
        return False
    for raw_line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "BUZZ_API_KEY":
            key = value.strip().strip("'\"")
            return bool(key and key != PLACEHOLDER)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the wallet-monitor desktop widget.")
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="keep the widget attached to this terminal so errors stay visible",
    )
    arguments, app_arguments = parser.parse_known_args()

    python = environment_python(windowed=not arguments.foreground)
    if not python.exists():
        print("The local Python environment is missing. Run: python setup_monitor.py", file=sys.stderr)
        return 1
    if not configured():
        print("BUZZ_API_KEY is not configured. Run setup_monitor.py or edit .env.", file=sys.stderr)
        return 1

    command = [str(python), str(APP_FILE), *app_arguments]
    if arguments.foreground:
        return subprocess.call(command, cwd=PROJECT_DIR)

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        command,
        cwd=PROJECT_DIR,
        creationflags=creation_flags,
        close_fds=True,
    )
    print("Wallet Monitor started.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())