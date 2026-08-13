import json
import threading

from .paths import state_root

STATE_FILE = "state.json"

_lock = threading.RLock()


def _read(name, default):
    try:
        with open(state_root() / name, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default() if callable(default) else default


def _write(name, data):
    root = state_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / name
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_state():
    with _lock:
        return _read(STATE_FILE, dict)


def _mutate_state(mutate):
    with _lock:
        state = _read(STATE_FILE, dict)
        mutate(state)
        _write(STATE_FILE, state)
        return state


def record_appimage(app_id, filename, tag):
    _mutate_state(lambda s: s.setdefault("appimages", {}).__setitem__(app_id, {"filename": filename, "tag": tag}))


def clear_appimage(app_id):
    _mutate_state(lambda s: s.setdefault("appimages", {}).pop(app_id, None))


def record_compat(app_id, dirname, tag):
    _mutate_state(lambda s: s.setdefault("compat", {}).__setitem__(app_id, {"dir": dirname, "tag": tag}))


def clear_compat(app_id):
    _mutate_state(lambda s: s.setdefault("compat", {}).pop(app_id, None))


def record_shortcut(app_id, steam_appid):
    def mutate(state):
        state.setdefault("shortcuts", {})[app_id] = int(steam_appid)
        _drop_pending(state, app_id)

    _mutate_state(mutate)


def clear_shortcut(app_id):
    _mutate_state(lambda s: s.setdefault("shortcuts", {}).pop(app_id, None))


def shortcuts():
    return load_state().get("shortcuts") or {}


def _drop_pending(state, app_id):
    pending = state.get("pendingShortcuts") or []
    if app_id in pending:
        state["pendingShortcuts"] = [entry for entry in pending if entry != app_id]


# Survives a closed panel and a backend restart, unlike the job list, which is
# pruned once a completed job passes its TTL.
def add_pending_shortcut(app_id):
    def mutate(state):
        pending = state.setdefault("pendingShortcuts", [])
        if app_id not in pending and app_id not in (state.get("shortcuts") or {}):
            pending.append(app_id)

    _mutate_state(mutate)


def clear_pending_shortcut(app_id):
    _mutate_state(lambda state: _drop_pending(state, app_id))


def pending_shortcuts():
    return list(load_state().get("pendingShortcuts") or [])
