# PyInstaller spec — builds `scele` as a --onedir bundle in dist/scele/.
#
#   pyinstaller packaging/scele.spec --clean --noconfirm
#
# onedir (not onefile) because onefile re-extracts the whole archive to a
# temp dir on every invocation — seconds per run. onedir starts in ~0.1s.
# The release workflow tars dist/scele/ into scele-<target>.tar.gz (.zip on
# Windows); install-bin.sh unpacks it and links dist/scele/scele onto PATH.
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# strip is only safe on Linux: on Windows the MSYS `strip` corrupts the bundled
# python3xx.dll ("Failed to load Python DLL"), and on macOS it can break arm64
# signatures.
strip_binaries = sys.platform.startswith("linux")

# Ship the package's non-Python files (the TUI stylesheet at
# scele/tui/styles/app.tcss). The TUI itself is optional: if `textual` was
# not installed at build time it is simply absent and `scele tui` prints an
# install hint instead.
datas = collect_data_files("scele")
hiddenimports = collect_submodules("scele")

try:  # only when the [tui] extra was installed into the build environment
    datas += collect_data_files("textual")
    hiddenimports += collect_submodules("textual")
except Exception:
    pass

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "playwright"],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="scele",
    debug=False,
    bootloader_ignore_signals=False,
    strip=strip_binaries,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=strip_binaries,
    upx=False,
    name="scele",
)
