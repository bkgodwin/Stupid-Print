import argparse
import tkinter as tk

from . import __version__
from .app import App


def main():
    parser = argparse.ArgumentParser(prog="StupidPrint")
    parser.add_argument("--version", action="version", version=f"Stupid Print {__version__}")
    parser.parse_args()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
