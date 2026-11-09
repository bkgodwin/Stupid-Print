#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"

tk_ready() {
    "$@" -c 'import sys, tkinter; tkinter.Tcl(); sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1
}

system_python() {
    local candidate
    for candidate in python3 /usr/bin/python3; do
        if tk_ready "$candidate" && "$candidate" -c 'import ensurepip' >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null; then
        sudo "$@"
    else
        return 1
    fi
}

install_tk() {
    if command -v apt-get >/dev/null; then
        as_root apt-get install python3 python3-tk python3-venv
    elif command -v dnf >/dev/null; then
        as_root dnf install python3 python3-tkinter
    elif command -v pacman >/dev/null; then
        as_root pacman -S --needed python tk
    else
        return 1
    fi
}

venv=.venv
rebuilt=0
if [ -d "$venv" ] && ! tk_ready "$venv/bin/python"; then
    venv=.venv-tk
fi
if ! tk_ready "$venv/bin/python"; then
    if ! python=$(system_python); then
        echo 'Installing Python, Tcl/Tk and venv support through your Linux package manager.'
        if ! install_tk || ! python=$(system_python); then
            echo 'Stupid Print needs Python 3.10 or later with Tcl/Tk and venv. Install these through your distribution and rerun the launcher.' >&2
            exit 1
        fi
    fi
    "$python" -m venv "$venv"
    rebuilt=1
fi
python="$venv/bin/python"
if ! "$python" -m pip --version >/dev/null 2>&1; then
    "$python" -m ensurepip --upgrade
fi
if [ "$rebuilt" -eq 1 ] || ! cmp -s requirements.txt "$venv/stupid-print-requirements.txt"; then
    "$python" -m pip install --disable-pip-version-check -r requirements.txt
    cp -- requirements.txt "$venv/stupid-print-requirements.txt"
fi
exec "$python" -m stupid_print
