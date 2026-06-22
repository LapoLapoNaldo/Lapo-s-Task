"""Configurações persistentes (XDG).

Guardado em ``$XDG_CONFIG_HOME/lapos-task/config.json`` (fallback
``~/.config/...``). As macros, por padrão, ficam em
``$XDG_DATA_HOME/lapos-task/macros`` (fallback ``~/.local/share/...``).
"""

import json
import os

APP = "lapos-task"


def _xdg(env, default):
    base = os.environ.get(env) or os.path.expanduser(default)
    return os.path.join(base, APP)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", "~/.config")
DATA_DIR = _xdg("XDG_DATA_HOME", "~/.local/share")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "speed": 1.0,
    "loop_count": 1,          # <=0 = infinito
    "macros_dir": os.path.join(DATA_DIR, "macros"),
    "last_dir": os.path.expanduser("~"),
    "hotkeys": {              # nomes de tecla evdev (ecodes.KEY_*)
        "record": "KEY_F9",
        "play": "KEY_F10",
        "stop": "KEY_ESC",
    },
}


def _merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    """Carrega o config mesclado com os defaults (defaults sãos sempre)."""
    cfg = dict(DEFAULTS)
    cfg["hotkeys"] = dict(DEFAULTS["hotkeys"])
    try:
        with open(CONFIG_PATH) as f:
            cfg = _merge(cfg, json.load(f))
    except (OSError, json.JSONDecodeError):
        pass
    os.makedirs(cfg["macros_dir"], exist_ok=True)
    return cfg


def save(cfg):
    """Persiste o config."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
