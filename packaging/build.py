"""Build the release packages on the native target OS with PyInstaller."""

import argparse
import importlib.metadata
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from stupid_print import __version__


def windows_resources(stage):
    icon = Image.new("RGBA", (256, 256))
    art = ImageDraw.Draw(icon)
    art.rounded_rectangle((5, 5, 250, 250), radius=46, fill="#7665fb")
    art.polygon(((58, 70), (151, 70), (198, 128), (151, 186), (58, 186)), fill="white")
    art.ellipse((145, 116, 169, 140), fill="#7665fb")
    for y in (110, 145):
        art.line((82, y, 121, y), fill="#7665fb", width=11)
    ico = stage / "stupid-print.ico"
    icon.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    version = stage / "version.txt"
    numbers = tuple(map(int, __version__.split("."))) + (0,)
    version.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0,
    OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'Stupid Print'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductName', 'Stupid Print'),
    StringStruct('ProductVersion', '{__version__}')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)""", encoding="utf-8")
    return ["--icon", str(ico), "--version-file", str(version)]


def copy_notices(bundle):
    from tkinter import TkVersion

    notices = bundle / "Third-party notices"
    notices.mkdir()
    for source in (HERE / "notices").iterdir():
        if source.name.startswith(("Tk-9-", "Tcl-9-")) and TkVersion < 9:
            continue
        shutil.copyfile(source, notices / source.name)
    names = ["Pillow", "pyserial", "openpyxl", "defusedxml", "et-xmlfile", "python-barcode",
             "zxing-cpp", "reportlab", "charset-normalizer", "PyInstaller"]
    if sys.platform == "linux":
        names.append("dbus-fast")
    components = [f"Python {platform.python_version()}"]
    for name in names:
        package = importlib.metadata.distribution(name)
        components.append(f"{name} {package.version}")
        for file in package.files or ():
            if not file.name.lower().startswith(("licen", "copying", "notice", "copyright")):
                continue
            source = Path(package.locate_file(file))
            if source.is_file():
                target = notices / name / file.name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(source, target)
    for name in ("LICENSE.txt", "LICENSE", "LICENSE.md"):
        source = Path(sys.base_prefix) / name
        if source.is_file():
            shutil.copyfile(source, notices / "Python-LICENSE.txt")
            break
    if sys.platform == "linux":
        # System libraries collected by PyInstaller retain their distribution notices.
        ubuntu_docs = Path("/usr/share/doc")
        for path in bundle.joinpath("_internal").glob("lib*.so*"):
            if path.is_symlink():
                continue
            query = subprocess.run(["dpkg-query", "-S", f"*/{path.name}"], capture_output=True, text=True)
            for line in query.stdout.splitlines():
                name = line.split(":", 1)[0]
                source = ubuntu_docs / name / "copyright"
                if source.is_file():
                    shutil.copyfile(source, notices / f"{name}-copyright.txt")
    (notices / "Components.txt").write_text("\n".join(components) + "\n", encoding="utf-8")


def debian_package(bundle, stage, out):
    tree = stage / "deb"
    control = tree / "DEBIAN"
    control.mkdir(parents=True)
    (control / "control").write_text(f"""Package: stupid-print
Version: {__version__}
Architecture: amd64
Maintainer: Stupid Print <137120064+bkgodwin@users.noreply.github.com>
Section: graphics
Priority: optional
Depends: libc6 (>= 2.35), libx11-6, libxext6, libxrender1, libxft2, fontconfig
Recommends: bluez, fonts-dejavu-core
Homepage: https://github.com/bkgodwin/Stupid-Print
Description: Desktop label designer for Bluetooth thermal printers
 Design, batch, export and print labels for the Phomemo D30 and Nelko P21.
""", encoding="utf-8")
    shutil.copytree(bundle, tree / "opt/stupid-print", symlinks=True)
    for source, target in (("stupid-print.desktop", "usr/share/applications/stupid-print.desktop"),
                           ("stupid-print.svg", "usr/share/icons/hicolor/scalable/apps/stupid-print.svg")):
        dest = tree / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / source, dest)
    commands = tree / "usr/bin"
    commands.mkdir(parents=True)
    (commands / "stupid-print").symlink_to("../../opt/stupid-print/StupidPrint")
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(tree),
                    str(out / f"stupid-print_{__version__}_amd64.deb")], check=True)


def build(out):
    if sys.platform not in ("win32", "linux") or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("Release packaging supports Windows and Linux on x86-64.")
    windows = sys.platform == "win32"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-", dir=out) as work:
        stage = Path(work)
        args = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--noupx", "--name", "StupidPrint",
            "--paths", str(ROOT), "--distpath", str(stage), "--workpath", str(stage / "build"),
            "--specpath", str(stage), "--add-data", f"{ROOT / 'stupid_print/assets'}:stupid_print/assets",
            "--hidden-import", "PIL._imagingtk", "--hidden-import", "PIL._tkinter_finder",
        ]
        if windows:
            args.extend(["--windowed", *windows_resources(stage)])
        subprocess.run([*args, str(HERE / "entrypoint.py")], cwd=ROOT, check=True)
        bundle = stage / "StupidPrint"
        shutil.copyfile(ROOT / "README.md", bundle / "README.md")
        copy_notices(bundle)
        if windows:
            (bundle / "portable.flag").touch()
            archive = out / f"Stupid-Print-{__version__}-Windows-x64-Portable.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
                for file in sorted(bundle.rglob("*")):
                    if file.is_file():
                        package.write(file, file.relative_to(stage))
        else:
            archive = out / f"Stupid-Print-{__version__}-Linux-x86_64.tar.gz"
            with tarfile.open(archive, "w:gz", compresslevel=6) as package:
                package.add(bundle, arcname="StupidPrint")
            debian_package(bundle, stage, out)
        print(archive)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    build(parser.parse_args().out.resolve())
