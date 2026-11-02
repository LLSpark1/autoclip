# PyInstaller recipe for AutoClip Studio.  Build with:  pyinstaller autoclip.spec
import sys

import cv2
from PyInstaller.utils.hooks import collect_all

datas = [("fonts", "fonts"),
         (cv2.data.haarcascades + "haarcascade_frontalface_default.xml", "cv2/data")]
binaries, hiddenimports = [], []
for package in ["gradio", "gradio_client", "safehttpx", "groovy", "faster_whisper",
                "ctranslate2", "imageio_ffmpeg", "webview"]:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["app.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["torch", "tensorflow", "matplotlib", "tkinter"],
    # Gradio reads its own source code at runtime, so keep it as .py files.
    module_collection_mode={"gradio": "py", "gradio_client": "py"},
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AutoClip Studio",
    console=False,
    icon="assets/icon.ico" if sys.platform == "win32" else "assets/icon.png",
)
coll = COLLECT(exe, a.binaries, a.datas, name="AutoClip Studio")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AutoClip Studio.app",
        icon="assets/icon.png",
        bundle_identifier="studio.autoclip.app",
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "1.0.0"},
    )
