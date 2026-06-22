"""Persistência de macros em JSON.

Formato v1 (com metadados)::

    {
      "version": 1,
      "name": "macro_123",
      "created": 1782090011.0,
      "duration": 4.32,
      "event_count": 320,
      "events": [{"t": .., "type": .., "code": .., "value": ..}, ...]
    }

O formato v0 antigo era uma lista crua de eventos (``[{...}, ...]``); ele
continua sendo carregável — :func:`load` detecta e migra em memória.
"""

import json
import os
import time

FORMAT_VERSION = 2
_REQUIRED_EVENT_KEYS = {"t", "type", "code", "value"}


class MacroError(Exception):
    """Erro de leitura/validação de macro."""


def to_signed32(value):
    """Reinterpreta ``value`` como int32 com sinal.

    O ``value`` de um ``input_event`` é ``__s32`` (com sinal). O recorder antigo
    lia como *unsigned*, então deltas negativos de mouse viravam números gigantes
    (ex.: -1 -> 4294967295). Aqui desfazemos isso: qualquer valor >= 2^31 é um
    negativo "embrulhado". Valores normais (0/1/2, deltas pequenos) passam intactos.
    """
    value = int(value)
    if value >= 0x80000000:
        value -= 0x100000000
    return value


def _sanitize(events):
    """Normaliza os ``value`` dos eventos para int32 com sinal (in place)."""
    for e in events:
        e["value"] = to_signed32(e["value"])
    return events


def _validate_events(events):
    if not isinstance(events, list) or not events:
        raise MacroError("Macro sem eventos ou em formato inválido.")
    for i, e in enumerate(events):
        if not isinstance(e, dict) or not _REQUIRED_EVENT_KEYS <= e.keys():
            raise MacroError(f"Evento {i} inválido (campos esperados: t/type/code/value).")
    return events


def _duration(events):
    return round(events[-1]["t"], 6) if events else 0.0


def build_macro(events, name, start_pos=None, position_log=None):
    """Monta o dict v2 a partir dos eventos."""
    return {
        "version": FORMAT_VERSION,
        "name": name,
        "created": time.time(),
        "duration": _duration(events),
        "event_count": len(events),
        "start_pos": list(start_pos) if start_pos else None,
        "position_checkpoints": position_log or [],
        "events": events,
    }


def save(events, path, name=None, start_pos=None, position_log=None):
    """Salva ``events`` em ``path`` no formato v2. Retorna o path."""
    _validate_events(events)
    if name is None:
        name = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(build_macro(events, name, start_pos, position_log), f, indent=2)
    return path


def load(path):
    """Carrega uma macro de ``path`` e devolve o dict v1 (migrando v0)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise MacroError(f"Não foi possível ler '{path}': {exc}") from exc

    if isinstance(data, list):  # v0: lista crua de eventos
        events = _sanitize(_validate_events(data))
        name = os.path.splitext(os.path.basename(path))[0]
        return build_macro(events, name)

    if isinstance(data, dict) and "events" in data:
        _sanitize(_validate_events(data["events"]))
        data.setdefault("version", FORMAT_VERSION)
        data.setdefault("name", os.path.splitext(os.path.basename(path))[0])
        data.setdefault("event_count", len(data["events"]))
        data.setdefault("duration", _duration(data["events"]))
        data.setdefault("start_pos", None)
        data.setdefault("position_checkpoints", [])
        return data

    raise MacroError(f"Formato de macro desconhecido em '{path}'.")


def load_events(path):
    """Atalho: carrega só a lista de eventos."""
    return load(path)["events"]


def list_macros(directory):
    """Lista as macros (.json) de ``directory`` como dicts de resumo."""
    if not os.path.isdir(directory):
        return []
    out = []
    for fn in sorted(os.listdir(directory)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(directory, fn)
        try:
            data = load(path)
        except MacroError:
            continue
        out.append(
            {
                "path": path,
                "name": data.get("name", fn[:-5]),
                "file": fn,
                "event_count": data.get("event_count", 0),
                "duration": data.get("duration", 0.0),
            }
        )
    return out


def export(src_path, dst_path):
    """Exporta (copia validando) a macro de ``src_path`` para ``dst_path``."""
    data = load(src_path)
    if os.path.isdir(dst_path):
        dst_path = os.path.join(dst_path, os.path.basename(src_path))
    if not dst_path.endswith(".json"):
        dst_path += ".json"
    os.makedirs(os.path.dirname(os.path.abspath(dst_path)) or ".", exist_ok=True)
    with open(dst_path, "w") as f:
        json.dump(data, f, indent=2)
    return dst_path


def import_macro(src_path, dest_dir):
    """Importa ``src_path`` para ``dest_dir`` (valida e normaliza p/ v1)."""
    data = load(src_path)
    os.makedirs(dest_dir, exist_ok=True)
    name = data.get("name") or os.path.splitext(os.path.basename(src_path))[0]
    dst_path = os.path.join(dest_dir, f"{name}.json")
    # evita sobrescrever uma macro existente de mesmo nome
    base, n = dst_path[:-5], 1
    while os.path.exists(dst_path):
        dst_path = f"{base}_{n}.json"
        n += 1
    with open(dst_path, "w") as f:
        json.dump(data, f, indent=2)
    return dst_path
