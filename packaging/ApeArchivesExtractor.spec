# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec di base. Va eseguito dal root del progetto dopo:
#   pip install -e ".[package]"

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from pathlib import Path

block_cipher = None
app_name = "ApeArchivesExtractor"
app_version = "1.0.0"
bundle_identifier = "com.giancagis.apearchivesextractor"
is_windows = sys.platform.startswith("win")
is_macos = sys.platform == "darwin"
project_root = Path(SPECPATH).parent
src_root = project_root / "src"
entry_point = src_root / "apearchivesextractor" / "gui" / "app.py"

hiddenimports = collect_submodules("py7zr")
datas = collect_data_files("apearchivesextractor")
assets_dir = project_root / "src" / "apearchivesextractor" / "assets"
app_icon = assets_dir / ("apearchivesextractor_app.icns" if is_macos else "apearchivesextractor_app.ico")
app_manifest = project_root / "packaging" / "ApeArchivesExtractor.exe.manifest"
exe_options = {
    "icon": str(app_icon),
}
if is_windows:
    exe_options["manifest"] = str(app_manifest)


a = Analysis(
    [str(entry_point)],
    pathex=[str(src_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=is_macos,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **exe_options,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)

if is_macos:
    app = BUNDLE(
        coll,
        name=f"{app_name}.app",
        icon=str(app_icon),
        bundle_identifier=bundle_identifier,
        info_plist={
            "CFBundleName": app_name,
            "CFBundleDisplayName": app_name,
            "CFBundleShortVersionString": app_version,
            "CFBundleVersion": app_version,
            "CFBundlePackageType": "APPL",
            "CFBundleSignature": "AAEx",
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "ZIP archive",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["public.zip-archive"],
                    "CFBundleTypeExtensions": ["zip"],
                },
                {
                    "CFBundleTypeName": "7-Zip archive",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["org.7-zip.7-zip-archive"],
                    "CFBundleTypeExtensions": ["7z"],
                },
                {
                    "CFBundleTypeName": "RAR and multi-volume archive",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "CFBundleTypeExtensions": (
                        ["rar", "001"]
                        + [f"r{index:02d}" for index in range(100)]
                        + [f"z{index:02d}" for index in range(1, 100)]
                    ),
                },
                {
                    "CFBundleTypeName": "Compressed tar archive",
                    "CFBundleTypeRole": "Viewer",
                    "LSHandlerRank": "Alternate",
                    "LSItemContentTypes": ["org.gnu.gnu-zip-tar-archive"],
                    "CFBundleTypeExtensions": ["tar.gz", "tgz"],
                },
            ],
        },
    )
