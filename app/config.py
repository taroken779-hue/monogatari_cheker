"""Machine-local tool paths; empty values use PATH."""
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def settings():
    path = ROOT / 'config.local.json'
    if not path.exists(): return {}
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict): raise ValueError('config.local.json must be an object')
    return data

def tool_path(name):
    value = os.environ.get(name.upper() + '_PATH') or settings().get(name) or shutil.which(name)
    if not isinstance(value, str) or not value: raise ValueError(f'{name}がありません。config.local.jsonに実行ファイルのパスを設定してください。')
    path = Path(value).expanduser()
    if not path.is_absolute(): path = ROOT / path
    if not path.is_file(): raise ValueError(f'{name}の設定パスに実行ファイルがありません。')
    return str(path)
