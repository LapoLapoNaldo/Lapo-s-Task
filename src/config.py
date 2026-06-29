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
    """Carrega o config mesclado com os defaults (defaults sempre presentes)."""
    cfg = dict(DEFAULTS)
    cfg["hotkeys"] = dict(DEFAULTS["hotkeys"])
    try:
        with open(CONFIG_PATH) as f:
            cfg = _merge(cfg, json.load(f))
    except (OSError, json.JSONDecodeError):
        pass
    # macros_dir vindo do config pode ser inválido/sem permissão: faz fallback
    # para o default em vez de derrubar o app no startup.
    try:
        os.makedirs(cfg["macros_dir"], exist_ok=True)
    except OSError:
        cfg["macros_dir"] = DEFAULTS["macros_dir"]
        try:
            os.makedirs(cfg["macros_dir"], exist_ok=True)
        except OSError:
            pass
    return cfg


def hotkey_codes(cfg):
    """Conjunto de keycodes evdev (int) das hotkeys configuradas.

    Usado para ignorar as próprias teclas de atalho durante a gravação, evitando
    que o clique em "parar" entre na macro. Centraliza a lógica antes duplicada
    no CLI e na UI.
    """
    from evdev import ecodes

    hk = cfg.get("hotkeys", {})
    return {
        code
        for name in hk.values()
        if (code := getattr(ecodes, name, None)) is not None
    }


def save(cfg):
    """Persiste o config."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
