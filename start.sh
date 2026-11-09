#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if ! command -v python3 >/dev/null || ! python3 -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 10))'; then
    echo 'Stupid Print needs Python 3.10 or newer with Tcl/Tk.' >&2
    echo 'On Debian/Ubuntu, run sudo apt install python3 python3-tk python3-venv' >&2
    echo 'On Fedora, run sudo dnf install python3 python3-tkinter' >&2
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    if ! python3 -m venv .venv; then
        echo 'Install your distribution’s Python venv package (python3-venv on Debian/Ubuntu) and try again.' >&2
        exit 1
    fi
fi
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    .venv/bin/python -m ensurepip --upgrade
fi
if ! cmp -s requirements.txt .venv/stupid-print-requirements.txt; then
    .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
    cp -- requirements.txt .venv/stupid-print-requirements.txt
fi
exec .venv/bin/python -m stupid_print
