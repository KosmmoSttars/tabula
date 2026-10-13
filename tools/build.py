"""Builds a portable Tabula for Windows with PyInstaller.

    .venv\\Scripts\\pip install pyinstaller
    .venv\\Scripts\\python tools/build.py

Result: dist/Tabula/ (Tabula.exe and its libraries) and dist/Tabula-<version>-windows.zip. Lives are kept
in dist/Tabula/lives next to the exe. PyTorch is the CPU build, which is most of the size.
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"
DIST = ROOT / "dist"

# Only whole packages Tabula never imports: PyTorch's own submodules import each other at startup,
# and leaving any of them out breaks `import torch` in the built app.
EXCLUDES = ["tkinter", "matplotlib", "scipy", "pandas", "IPython", "torchvision", "torchaudio", "pytest"]


def main() -> int:
    work = ROOT / "build"
    console = "--console" in sys.argv   # for debugging a build: errors show up in a console
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", "Tabula",
            "--console" if console else "--windowed",
            "--distpath", str(DIST), "--workpath", str(work / "pyi"), "--specpath", str(work),
            "--icon", str(ROOT / "web" / "icon.ico")]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    subprocess.run(args + [str(ROOT / "run.py")], check=True, cwd=ROOT)

    app = DIST / "Tabula"
    shutil.copy2(ROOT / "README.md", app / "README.md")
    shutil.copy2(ROOT / "LICENSE", app / "LICENSE.txt")

    check = subprocess.run([str(app / "Tabula.exe"), "--self-check"], capture_output=True, text=True, timeout=900)
    report = app / "tabula_check.txt"
    print(report.read_text(encoding="utf-8") if report.exists() else check.stdout + check.stderr)
    if check.returncode != 0:
        print("self-check FAILED")
        return 1
    report.unlink()

    archive = DIST / f"Tabula-{VERSION}-windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in app.rglob("*"):
            if f.is_file() and "lives" not in f.relative_to(app).parts:
                z.write(f, Path("Tabula") / f.relative_to(app))
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print(f"done   {app} ({size / 2**20:.0f} MB), {archive.name} ({archive.stat().st_size / 2**20:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
