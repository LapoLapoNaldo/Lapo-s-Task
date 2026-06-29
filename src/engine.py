"""Motor de gravação e reprodução de macros via evdev.

No Wayland/Hyprland não existe API de captura/injeção de input em espaço de
usuário (X11), então lemos os eventos crus de ``/dev/input/event*`` e os
reinjetamos por ``/dev/uinput``. A biblioteca ``evdev`` cuida do parsing do
``struct input_event`` (incluindo o ``value`` *signed* e o buffer completo),
então não há manipulação manual de bytes aqui.

Cada evento gravado é um dict ``{"t", "type", "code", "value"}`` onde ``t`` é o
instante (em segundos) relativo ao início da gravação. Gravamos também os
eventos ``EV_SYN/SYN_REPORT`` para preservar o agrupamento original — e, no
playback, é o ``syn()`` correspondente que faz o kernel processar o lote (a
ausência dele era o motivo de o playback antigo "não fazer nada").
"""

import errno
import functools
import select
import shutil
import subprocess
import threading
import time

from evdev import InputDevice, UInput, ecodes, list_devices

from storage import to_signed32

# Tipos de evento que nos interessam: teclas/botões, movimento relativo do
# mouse, roda, e o sync que delimita cada lote.
_RECORDED_TYPES = (ecodes.EV_KEY, ecodes.EV_REL, ecodes.EV_SYN)

# Nome do nosso dispositivo virtual (UInput). Ignorado na captura p/ não criar
# feedback loop reinjetando os próprios eventos.
_VIRTUAL_NAME = "LaposTask"

# Capabilities consideradas "input de verdade" por padrão.
_DEFAULT_CAPS = (ecodes.EV_KEY, ecodes.EV_REL, ecodes.EV_ABS)


@functools.lru_cache(maxsize=1)
def _hyprctl():
    """Caminho do ``hyprctl`` (ou None), resolvido uma única vez por sessão."""
    return shutil.which("hyprctl")


def get_cursor_pos():
    """Posição absoluta (x, y) do cursor via hyprctl, ou None se indisponível.

    O mouse é gravado como movimento *relativo* (deltas), então sozinho ele não
    sabe de onde partiu. Capturamos a posição absoluta no início para o playback
    poder começar do mesmo ponto X.
    """
    if not _hyprctl():
        return None
    try:
        out = subprocess.run(
            ["hyprctl", "cursorpos"], capture_output=True, text=True, timeout=1
        ).stdout.strip()
        x, y = out.replace(" ", "").split(",")
        return int(x), int(y)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def warp_cursor(x, y):
    """Teleporta o cursor para (x, y) absoluto via hyprctl. Retorna sucesso."""
    if not _hyprctl():
        return False
    try:
        subprocess.run(
            ["hyprctl", "dispatch", "movecursor", str(int(x)), str(int(y))],
            capture_output=True, timeout=1,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def list_input_devices(require=_DEFAULT_CAPS):
    """InputDevices acessíveis com ao menos uma capability em ``require``.

    Dispositivos que não interessam (e os nossos virtuais) são **fechados** antes
    do retorno — evitando o vazamento de file descriptors que ocorria quando o
    chamador filtrava o resultado e descartava os ``InputDevice`` abertos.
    """
    devices = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except (PermissionError, OSError):
            continue
        caps = dev.capabilities()
        if dev.name == _VIRTUAL_NAME or not any(c in caps for c in require):
            dev.close()
            continue
        devices.append(dev)
    return devices


def _close_all(devices):
    for dev in devices:
        try:
            dev.close()
        except OSError:
            pass


class Recorder:
    """Grava eventos de input de todos os dispositivos em uma thread."""

    def __init__(self):
        self._thread = None
        self._running = False
        self.events = []
        self.start_pos = None  # posição absoluta do cursor no início

    @property
    def running(self):
        return self._running

    def start(self, callback=None, on_error=None, on_stop=None, ignore_keys=None):
        """Inicia a gravação em background.

        ``callback(event)`` é chamado para cada evento gravado; ``on_error(exc)``
        se algo falhar na thread; ``on_stop()`` ao encerrar (em qualquer caso),
        permitindo à UI reagir sem precisar fazer polling.
        """
        if self._running:
            return
        self.events = []
        self.start_pos = get_cursor_pos()
        self._running = True
        self._thread = threading.Thread(
            target=self._run, args=(callback, on_error, on_stop, ignore_keys),
            daemon=True,
        )
        self._thread.start()

    def _run(self, callback, on_error, on_stop, ignore_keys=None):
        devices = []
        ignore_keys = ignore_keys or set()
        try:
            devices = list_input_devices()
            if not devices:
                raise RuntimeError(
                    "Nenhum dispositivo de input acessível. "
                    "Verifique se você está no grupo 'input'."
                )
            fd_map = {dev.fd: dev for dev in devices}
            start = time.monotonic()

            while self._running:
                ready, _, _ = select.select(fd_map, [], [], 0.02)
                for fd in ready:
                    dev = fd_map[fd]
                    try:
                        for event in dev.read():
                            if event.type not in _RECORDED_TYPES:
                                continue
                            if event.type == ecodes.EV_KEY and event.code in ignore_keys:
                                continue
                            entry = {
                                "t": round(time.monotonic() - start, 6),
                                "type": event.type,
                                "code": event.code,
                                "value": event.value,
                            }
                            self.events.append(entry)
                            if callback:
                                callback(entry)
                    except OSError as exc:
                        if getattr(exc, "errno", None) == errno.ENODEV:
                            # Dispositivo removido — tira do fd_map
                            fd_map.pop(fd, None)
                            try:
                                dev.close()
                            except OSError:
                                pass
                        # Outros OSError (incl. EAGAIN) ignoram
                    except BlockingIOError:
                        pass
        except Exception as exc:  # noqa: BLE001 - propaga p/ a UI
            if on_error:
                on_error(exc)
        finally:
            self._running = False
            _close_all(devices)
            if on_stop:
                on_stop()

    def stop(self):
        self._running = False
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)


class Player:
    """Reproduz eventos gravados via UInput, em uma thread."""

    def __init__(self):
        self._thread = None
        self._running = False

    @property
    def running(self):
        return self._running

    def play(self, events, speed=1.0, loop=1, start_pos=None,
             on_done=None, on_error=None, on_progress=None):
        """Reproduz ``events``. ``loop`` = número de repetições (<=0 = infinito
        até :meth:`stop`). ``start_pos`` = (x, y) absoluto para o cursor iniciar.
        ``on_progress(elapsed, duration, cur_loop, total_loops)`` é chamado ~30×/s.
        Roda em background."""
        if self._running or not events:
            if on_done:
                on_done()
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(events, speed, loop, start_pos, on_done, on_error, on_progress),
            daemon=True,
        )
        self._thread.start()

    def _build_uinput(self, events):
        keys, rels = set(), set()
        for e in events:
            if e["type"] == ecodes.EV_KEY:
                keys.add(e["code"])
            elif e["type"] == ecodes.EV_REL:
                rels.add(e["code"])
        cap = {}
        if keys:
            cap[ecodes.EV_KEY] = sorted(keys)
        if rels:
            cap[ecodes.EV_REL] = sorted(rels)
        if not cap:
            cap = {ecodes.EV_KEY: [ecodes.KEY_A]}
        return UInput(cap, name=_VIRTUAL_NAME)

    def _interruptible_sleep(self, delay):
        """Dorme ``delay`` segundos em fatias, respondendo ao stop sem busy-wait."""
        end = time.monotonic() + delay
        while self._running:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.01, remaining))

    def _warp_to_start(self, start_pos):
        """Posiciona o cursor no ponto inicial, conferindo uma vez."""
        if not warp_cursor(int(start_pos[0]), int(start_pos[1])):
            return  # sem hyprctl: nada a fazer, não desperdiça o sleep
        time.sleep(0.15)
        actual = get_cursor_pos()
        if actual and (abs(actual[0] - start_pos[0]) > 2
                       or abs(actual[1] - start_pos[1]) > 2):
            warp_cursor(int(start_pos[0]), int(start_pos[1]))

    def _run(self, events, speed, loop, start_pos, on_done, on_error, on_progress):
        ui = None
        pressed = set()
        speed = speed if speed > 0 else 1.0
        duration = events[-1]["t"] if events else 0.0
        try:
            ui = self._build_uinput(events)
            # Aguarda o sistema/compositor registrar o novo dispositivo virtual
            time.sleep(0.2)
            has_syn = any(e["type"] == ecodes.EV_SYN for e in events)
            iteration = 0
            last_progress = 0.0
            while self._running and (loop <= 0 or iteration < loop):
                if on_progress:
                    on_progress(0.0, duration, iteration + 1, loop)
                # cada repetição parte do mesmo ponto onde a gravação começou
                if start_pos:
                    self._warp_to_start(start_pos)
                prev = 0.0
                for e in events:
                    if not self._running:
                        break
                    delay = (e["t"] - prev) / speed
                    if delay > 0:
                        self._interruptible_sleep(delay)
                    prev = e["t"]

                    # to_signed32: defesa contra macros gravadas pelo bug unsigned
                    ui.write(e["type"], e["code"], to_signed32(e["value"]))
                    if e["type"] == ecodes.EV_SYN and e["code"] == ecodes.SYN_REPORT:
                        ui.syn()
                    else:
                        if not has_syn:
                            ui.syn()
                        if e["type"] == ecodes.EV_KEY:
                            if e["value"]:
                                pressed.add(e["code"])
                            else:
                                pressed.discard(e["code"])

                    # reporta progresso ~30×/s (a cada ~33ms)
                    if on_progress:
                        now = time.monotonic()
                        if now - last_progress >= 0.033:
                            on_progress(e["t"], duration, iteration + 1, loop)
                            last_progress = now
                # garante um sync ao fim do lote, caso a macro não termine em SYN
                ui.syn()
                iteration += 1
                if on_progress:
                    on_progress(duration, duration, iteration, loop)
                if self._running and (loop <= 0 or iteration < loop):
                    time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            if on_error:
                on_error(exc)
        finally:
            # solta qualquer tecla que tenha ficado pressionada -> evita "tecla presa"
            if ui is not None:
                try:
                    for code in pressed:
                        ui.write(ecodes.EV_KEY, code, 0)
                    ui.syn()
                except OSError:
                    pass
                try:
                    ui.close()
                except OSError:
                    pass
            self._running = False
            if on_done:
                on_done()

    def stop(self):
        self._running = False
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)
