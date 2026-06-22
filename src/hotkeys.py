"""Hotkeys globais lendo ``/dev/input`` diretamente.

No Wayland não há API de atalho global em espaço de usuário, então
escutamos os eventos de tecla crus (mesmo mecanismo da gravação). Isso faz os
atalhos funcionarem com a janela em background — e permite parar a gravação por
tecla, sem registrar o clique na própria UI.

As teclas são identificadas por nome de ``ecodes`` (ex.: ``"KEY_F9"``).
"""

import errno
import select
import threading

from evdev import ecodes

from engine import list_input_devices


class HotkeyListener:
    """Escuta teclas e dispara callbacks. Roda em uma thread daemon."""

    def __init__(self, bindings, on_error=None):
        """``bindings``: dict ``{nome_da_acao: ("KEY_F9", callback)}``."""
        self._running = False
        self._thread = None
        self._on_error = on_error
        self._codes = {}  # keycode (int) -> callback
        self.set_bindings(bindings)

    def set_bindings(self, bindings):
        codes = {}
        for _action, (key_name, callback) in bindings.items():
            code = getattr(ecodes, key_name, None)
            if code is not None and callback is not None:
                codes[code] = callback
        self._codes = codes

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        devices = []
        try:
            devices = [d for d in list_input_devices()
                       if ecodes.EV_KEY in d.capabilities()]
            if not devices:
                return
            fd_map = {d.fd: d for d in devices}
            while self._running:
                ready, _, _ = select.select(fd_map, [], [], 0.02)
                for fd in ready:
                    try:
                        for event in fd_map[fd].read():
                            # value == 1 -> key down (ignora repeat=2 e up=0)
                            if event.type == ecodes.EV_KEY and event.value == 1:
                                cb = self._codes.get(event.code)
                                if cb:
                                    cb()
                    except OSError as exc:
                        if getattr(exc, "errno", None) == errno.ENODEV:
                            dev = fd_map.pop(fd, None)
                            if dev:
                                try:
                                    dev.close()
                                except OSError:
                                    pass
                    except BlockingIOError:
                        pass
        except Exception as exc:  # noqa: BLE001
            if self._on_error:
                self._on_error(exc)
        finally:
            for d in devices:
                try:
                    d.close()
                except OSError:
                    pass

    def stop(self):
        self._running = False
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)
