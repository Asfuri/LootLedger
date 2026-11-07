import os
from pathlib import Path
from importlib.metadata import distribution

root = Path(SPECPATH)
helper = root / 'replay-reader' / 'publish' / 'LootLedger.ReplayReader.exe'
if not helper.is_file():
    raise SystemExit('Build the replay reader first (build.ps1 publishes it to replay-reader/publish).')

notices = [('LICENSE', '.'), ('THIRD_PARTY.md', '.'), (str(helper), 'replay-reader'),
           ('replay-reader/vendor/FortniteReplayDecompressor/LICENSE', 'licenses/FortniteReplayDecompressor'),
           ('replay-reader/vendor/FortniteReplayDecompressor/VENDORED.md', 'licenses/FortniteReplayDecompressor')]
# Material Symbols icon font (Apache-2.0). The app loads it from lootledger/assets/fonts at runtime.
fonts = root / 'lootledger' / 'assets' / 'fonts'
notices += [(str(fonts / 'MaterialSymbolsRounded.ttf'), 'lootledger/assets/fonts'),
            (str(fonts / 'LICENSE-MaterialSymbols.txt'), 'licenses/MaterialSymbols')]
# The replay reader embeds the .NET runtime (MIT); keep its licence and third-party notices.
dotnet_root = Path(os.environ.get('LOOTLEDGER_DOTNET_ROOT', root / '.dotnet'))
for name in ('LICENSE.txt', 'ThirdPartyNotices.txt'):
    if (dotnet_root / name).is_file():
        notices.append((str(dotnet_root / name), 'licenses/dotnet-runtime'))
for package in ('PySide6-Essentials', 'shiboken6'):
    installed = distribution(package)
    for entry in installed.files or []:
        if 'license' in str(entry).lower() or 'copying' in entry.name.lower() or 'notice' in entry.name.lower():
            source = installed.locate_file(entry)
            if source.is_file():
                notices.append((str(source), str('licenses/' + package + '/' + str(entry.parent))))

a = Analysis(
    ['run.py'], pathex=[], binaries=[], datas=notices, hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[
        # The retired screen detector's dependencies are not part of the desktop app.
        'cv2', 'numpy', 'onnxruntime', 'mss', 'winrt',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtPdf',
        'PySide6.QtQml', 'PySide6.QtQuick', 'pytest', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
# One-file build: a single LootLedger.exe that unpacks itself to a temp folder at launch.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='LootLedger',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
