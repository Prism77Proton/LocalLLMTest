"""Remembered model-server API keys.

A key you type at the hidden prompt can be saved so the next run does not ask again.
The file lives in your own config folder, never in the repository or a run folder
(those get zipped and shared): $XDG_CONFIG_HOME/llmtest/keys.json, else
~/.config/llmtest/keys.json. It is plain JSON readable only by you (mode 0600, folder
0700), one key per server URL. `llmtest --forget-key` deletes it.
"""
import json
import os
from pathlib import Path


def path():
    base = os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base) / 'llmtest' / 'keys.json'


def _read():
    try:
        data = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {url: key for url, key in data.items() if isinstance(url, str) and isinstance(key, str) and key}


def _write(data):
    target = path()
    if not data:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp')
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, 0o600)  # in case the file already existed with looser permissions
    temp.replace(target)


def load(server):
    """The remembered key for a server URL, or ''."""
    return _read().get(server, '')


def save(server, key):
    data = _read()
    data[server] = key
    _write(data)


def forget(servers=None):
    """Delete the remembered key for each URL in servers, or every key when servers is None.
    Returns how many keys were removed."""
    data = _read()
    doomed = list(data) if servers is None else [url for url in servers if url in data]
    for url in doomed:
        del data[url]
    if doomed:
        _write(data)
    return len(doomed)
