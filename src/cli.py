#!/usr/bin/env python3
"""Interface de linha de comando do MacroRecorder.

Uso: ``python src/cli.py <comando>`` (ou sem comando -> GUI).
"""

import argparse
import os
import sys
import time

# garante que os módulos irmãos (engine, storage, ...) sejam importáveis
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg_mod
import storage
from engine import Recorder, Player


def cmd_gui(args, cfg):
    from ui import main
    main()


def cmd_record(args, cfg):
    rec = Recorder()
    print("Gravando... Ctrl+C para parar.")
    ignore_keys = cfg_mod.hotkey_codes(cfg)
    rec.start(ignore_keys=ignore_keys)
    try:
        while rec.running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        rec.stop()

    if not rec.events:
        print("Nenhum evento gravado.")
        return
    name = storage.safe_name(args.output or f"macro_{int(time.time())}")
    path = os.path.join(cfg["macros_dir"], f"{name}.json")
    storage.save(rec.events, path, name, start_pos=rec.start_pos)
    pos = f", início @ {rec.start_pos}" if rec.start_pos else ""
    print(f"Salvo: {path} ({len(rec.events)} eventos{pos})")


def cmd_play(args, cfg):
    try:
        data = storage.load(_resolve(args.input, cfg))
    except storage.MacroError as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)
    events = data["events"]
    start_pos = data.get("start_pos")
    speed = args.speed if args.speed is not None else cfg["speed"]
    loop = args.loop if args.loop is not None else cfg["loop_count"]
    print(f"Reproduzindo {len(events)} eventos (speed={speed}, loop={loop or '∞'})...")
    player = Player()
    done = {"ok": False}
    player.play(events, speed=speed, loop=loop, start_pos=start_pos,
                on_done=lambda: done.update(ok=True))
    try:
        while not done["ok"]:
            time.sleep(0.05)
    except KeyboardInterrupt:
        player.stop()
    print("Fim.")


def cmd_macros(args, cfg):
    macros = storage.list_macros(cfg["macros_dir"])
    if not macros:
        print("Nenhuma macro salva.")
        return
    for m in macros:
        print(f"  {m['file']:30s} {m['event_count']:6d} ev   {m['duration']:.2f}s")


def cmd_export(args, cfg):
    dst = storage.export(_resolve(args.macro, cfg), args.dest)
    print(f"Exportado: {dst}")


def cmd_import(args, cfg):
    dst = storage.import_macro(args.path, cfg["macros_dir"])
    print(f"Importado: {dst}")


def _resolve(name, cfg):
    """Aceita caminho direto ou nome de macro na pasta padrão."""
    if os.path.exists(name):
        return name
    candidate = os.path.join(cfg["macros_dir"], name)
    if not candidate.endswith(".json"):
        candidate += ".json"
    return candidate


def main():
    p = argparse.ArgumentParser(description="Lapo's Task — TinyTask para Linux/Wayland")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="Interface gráfica (padrão)")

    rp = sub.add_parser("record", help="Gravar macro")
    rp.add_argument("-o", "--output", help="Nome da macro")

    pp = sub.add_parser("play", help="Reproduzir macro")
    pp.add_argument("input", help="Arquivo ou nome da macro")
    pp.add_argument("-s", "--speed", type=float, default=None, help="Velocidade")
    pp.add_argument("-l", "--loop", type=int, default=None, help="Repetições (0 = infinito)")

    sub.add_parser("macros", help="Listar macros salvas")

    ep = sub.add_parser("export", help="Exportar macro")
    ep.add_argument("macro", help="Arquivo ou nome da macro")
    ep.add_argument("dest", help="Destino (arquivo ou pasta)")

    ip = sub.add_parser("import", help="Importar macro")
    ip.add_argument("path", help="Arquivo .json a importar")

    args = p.parse_args()
    cfg = cfg_mod.load()

    handlers = {
        "gui": cmd_gui, "record": cmd_record, "play": cmd_play,
        "macros": cmd_macros, "export": cmd_export, "import": cmd_import,
    }
    handler = handlers.get(args.cmd, cmd_gui)
    try:
        handler(args, cfg)
    except storage.MacroError as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Erro de E/S: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
