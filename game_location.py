import json
import os
import re
import sys
from pathlib import Path


def settings_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PartyDashViewer' / 'settings.json'


def legacy_settings_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'UmaAssetExplorer' / 'settings.json'


def normalize_folder(path):
    path = Path(path)
    if path.is_file():
        path = path.parent
    candidate = path / 'asset' if (path / 'asset').is_dir() else path
    try:
        if candidate.name.casefold() == 'asset' and any(candidate.glob('*.bin')):
            return candidate.resolve()
    except OSError:
        pass
    return None


def remember_folder(path):
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'game_folder': str(path)}, ensure_ascii=False), encoding='utf-8')
    temporary.replace(target)


def discover_folders():
    candidates = []
    for remembered in (settings_path(), legacy_settings_path()):
        try:
            candidates.append(Path(json.loads(remembered.read_text(encoding='utf-8'))['game_folder']))
            break
        except (OSError, ValueError, KeyError, TypeError):
            continue
    app_dir = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
    candidates.extend([app_dir, *list(app_dir.parents)[:6], Path.cwd()])
    steam_roots = [Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Steam']
    if sys.platform == 'win32':
        import winreg
        for hive, key, value in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'), (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'), (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')]:
            try:
                with winreg.OpenKey(hive, key) as handle:
                    steam_roots.append(Path(winreg.QueryValueEx(handle, value)[0]))
            except OSError:
                pass
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key in (r'Software\Microsoft\Windows\CurrentVersion\Uninstall', r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        for index in range(winreg.QueryInfoKey(handle)[0]):
                            try:
                                with winreg.OpenKey(handle, winreg.EnumKey(handle, index)) as entry:
                                    name = str(winreg.QueryValueEx(entry, 'DisplayName')[0]).casefold()
                                    if 'party dash' in name:
                                        candidates.append(Path(winreg.QueryValueEx(entry, 'InstallLocation')[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
    libraries = set(steam_roots)
    for root in steam_roots:
        try:
            content = (root / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8')
            libraries.update(Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s*"([^"]+)"', content))
        except OSError:
            pass
    for library in libraries:
        try:
            candidates.extend(p for p in (library / 'steamapps/common').iterdir() if 'party' in p.name.casefold() and 'dash' in p.name.casefold())
        except OSError:
            pass
        try:
            for manifest in (library / 'steamapps').glob('appmanifest_*.acf'):
                content = manifest.read_text(encoding='utf-8')
                if 'party dash' in content.casefold():
                    match = re.search(r'"installdir"\s*"([^"]+)"', content)
                    if match:
                        candidates.append(library / 'steamapps/common' / match[1])
        except OSError:
            pass
    for drive in 'CDEFGHIJ':
        for base in ('Games', 'Jogos', 'SteamLibrary/steamapps/common'):
            folder = Path(f'{drive}:/') / base
            try:
                candidates.extend(p for p in folder.glob('*') if 'party dash' in p.name.casefold())
            except OSError:
                pass
    found = []
    for candidate in candidates:
        valid = normalize_folder(candidate)
        if valid and valid not in found:
            found.append(valid)
    return found
