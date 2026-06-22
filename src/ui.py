"""Interface gráfica (PySide6) do MacroRecorder.

As threads do motor (gravação/playback/hotkeys) nunca tocam widgets
diretamente: elas emitem ``Signal`` Qt, processados na thread da UI.
"""

import os
import time

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

import config as cfg_mod
import storage
from engine import Recorder, Player
from hotkeys import HotkeyListener
from evdev import ecodes

# Paleta Catppuccin Mocha
BASE = "#1e1e2e"
SURFACE = "#313244"
TEXT = "#cdd6f4"
SUBTLE = "#7f849c"
GREEN = "#a6e3a1"
RED = "#f38ba8"
PEACH = "#fab387"
MAUVE = "#cba6f7"

STYLESHEET = f"""
QWidget {{ background: {BASE}; color: {TEXT}; font-family: monospace; }}
QLabel#timer {{ color: {GREEN}; }}
QLabel#status {{ color: {SUBTLE}; }}
QLabel.dim {{ color: {SUBTLE}; }}
QPushButton {{
    background: {SURFACE}; color: {TEXT}; border: none;
    border-radius: 8px; padding: 8px 10px; font-weight: bold;
}}
QPushButton:hover {{ background: #45475a; }}
QPushButton:disabled {{ color: {SUBTLE}; background: #292c3c; }}
QPushButton#rec {{ background: {RED}; color: {BASE}; }}
QPushButton#play {{ background: {GREEN}; color: {BASE}; }}
QPushButton#stop {{ background: {PEACH}; color: {BASE}; }}
QListWidget {{ background: {SURFACE}; border-radius: 8px; padding: 4px; }}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {MAUVE}; color: {BASE}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE}; border: 1px solid #45475a; border-radius: 6px; padding: 4px;
}}
QCheckBox {{ color: {TEXT}; }}
QProgressBar {{
    background: {SURFACE}; border: none; border-radius: 6px;
    height: 14px; text-align: center; font-size: 10px;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {MAUVE}, stop:1 {GREEN});
    border-radius: 6px;
}}
"""


def fmt_time(seconds):
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:06.3f}"


def fmt_key(name):
    """``KEY_F9`` -> ``F9``; ``KEY_ESC`` -> ``Esc``."""
    s = name.replace("KEY_", "")
    if s.startswith("F") and s[1:].isdigit():
        return s
    return s.capitalize()


class Bridge(QObject):
    """Sinais emitidos pelas threads do motor -> UI."""
    record_done = Signal()
    play_done = Signal()
    play_progress = Signal(float, float, int, int)  # elapsed, duration, cur_loop, total
    error = Signal(str)
    hotkey = Signal(str)


class MacroRecorderUI(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = cfg_mod.load()
        self.recorder = Recorder()
        self.player = Player()
        self.events = []
        self.start_pos = None
        self.position_checkpoints = []
        self.current_path = None
        self._rec_start = 0.0
        self._in_dialog = False  # bloqueia hotkeys enquanto diálogo modal estiver aberto
        self._rec_stopped = False  # evita dupla chamada do record_done

        self.bridge = Bridge()
        self.bridge.record_done.connect(self._on_record_done)
        self.bridge.play_done.connect(self._on_play_done)
        self.bridge.play_progress.connect(self._on_play_progress)
        self.bridge.error.connect(self._on_error)
        self.bridge.hotkey.connect(self._on_hotkey)

        self.setWindowTitle("Lapo's Task")
        self.setMinimumWidth(400)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()
        self._refresh_macros()

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        self._start_hotkeys()

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.timer_lbl = QLabel("00:00.000")
        self.timer_lbl.setObjectName("timer")
        self.timer_lbl.setAlignment(Qt.AlignCenter)
        f = self.timer_lbl.font()
        f.setPointSize(26)
        f.setBold(True)
        self.timer_lbl.setFont(f)
        root.addWidget(self.timer_lbl)

        btns = QHBoxLayout()
        self.rec_btn = QPushButton()
        self.rec_btn.setObjectName("rec")
        self.rec_btn.clicked.connect(self.start_record)
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("stop")
        self.stop_btn.clicked.connect(self.stop_all)
        self.stop_btn.setEnabled(False)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("play")
        self.play_btn.clicked.connect(self.start_play)
        self.play_btn.setEnabled(False)
        for b in (self.rec_btn, self.stop_btn, self.play_btn):
            b.setMinimumHeight(46)
            btns.addWidget(b)
        root.addLayout(btns)
        self._refresh_buttons()

        self.macros_list = QListWidget()
        self.macros_list.itemSelectionChanged.connect(self._on_select)
        self.macros_list.itemDoubleClicked.connect(lambda _: self.start_play())
        root.addWidget(self.macros_list)

        # ----------- barra de progresso + indicador de loop
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.loop_lbl = QLabel("")
        self.loop_lbl.setObjectName("status")
        self.loop_lbl.setAlignment(Qt.AlignCenter)
        self.loop_lbl.setVisible(False)
        root.addWidget(self.loop_lbl)

        # controles inline: velocidade + repetições + endless
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Velocidade"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 20.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setSuffix("×")
        self.speed_spin.setValue(self.cfg["speed"])
        self.speed_spin.valueChanged.connect(self._on_speed_changed)
        ctl.addWidget(self.speed_spin)
        ctl.addSpacing(12)
        ctl.addWidget(QLabel("Repetir"))
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(1, 100000)
        self.loop_spin.valueChanged.connect(self._on_loop_changed)
        ctl.addWidget(self.loop_spin)
        self.endless_chk = QCheckBox("∞ sem parar")
        self.endless_chk.toggled.connect(self._on_endless_toggled)
        ctl.addWidget(self.endless_chk)
        ctl.addStretch()
        root.addLayout(ctl)
        self._sync_loop_controls()

        bottom = QHBoxLayout()
        for text, slot in (
            ("Import", self.import_macro),
            ("Export", self.export_macro),
            ("Delete", self.delete_macro),
            ("⚙ Config", self.open_config),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bottom.addWidget(b)
        root.addLayout(bottom)

        self.status_lbl = QLabel("Pronto")
        self.status_lbl.setObjectName("status")
        root.addWidget(self.status_lbl)

    def _refresh_buttons(self):
        """Mostra a keybind atual embaixo de cada ação."""
        hk = self.cfg["hotkeys"]
        self.rec_btn.setText(f"●  REC\n{fmt_key(hk['record'])}")
        self.stop_btn.setText(f"■  STOP\n{fmt_key(hk['stop'])}")
        self.play_btn.setText(f"▶  PLAY\n{fmt_key(hk['play'])}")

    def _sync_loop_controls(self):
        """Reflete cfg['loop_count'] nos controles sem disparar sinais."""
        infinite = self.cfg["loop_count"] <= 0
        for w in (self.loop_spin, self.endless_chk):
            w.blockSignals(True)
        self.endless_chk.setChecked(infinite)
        self.loop_spin.setEnabled(not infinite)
        self.loop_spin.setValue(self.cfg["loop_count"] if not infinite else 1)
        for w in (self.loop_spin, self.endless_chk):
            w.blockSignals(False)

    # ------------------------------------------------------- controles
    def _on_speed_changed(self, v):
        self.cfg["speed"] = round(v, 3)
        cfg_mod.save(self.cfg)

    def _on_loop_changed(self, v):
        if not self.endless_chk.isChecked():
            self.cfg["loop_count"] = v
            cfg_mod.save(self.cfg)

    def _on_endless_toggled(self, checked):
        self.loop_spin.setEnabled(not checked)
        self.cfg["loop_count"] = 0 if checked else max(1, self.loop_spin.value())
        cfg_mod.save(self.cfg)

    # ------------------------------------------------------------ macros
    def _refresh_macros(self):
        self.macros_list.clear()
        for m in storage.list_macros(self.cfg["macros_dir"]):
            item = QListWidgetItem(
                f"{m['name']}    {m['event_count']} ev   {fmt_time(m['duration'])}"
            )
            item.setData(Qt.UserRole, m["path"])
            self.macros_list.addItem(item)

    def _selected_path(self):
        item = self.macros_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_select(self):
        path = self._selected_path()
        if not path:
            return
        try:
            data = storage.load(path)
            self.events = data["events"]
            self.start_pos = data.get("start_pos")
            self.position_checkpoints = data.get("position_checkpoints", [])
            self.current_path = path
            self.play_btn.setEnabled(bool(self.events) and not self._busy())
            pos = f"  @ {tuple(self.start_pos)}" if self.start_pos else ""
            n_chk = len(self.position_checkpoints)
            chk = f" +{n_chk} checkpoints" if n_chk else ""
            self.status_lbl.setText(
                f"{os.path.basename(path)} — {len(self.events)} eventos{pos}{chk}"
            )
        except storage.MacroError as e:
            self.events = []
            self.start_pos = None
            self.position_checkpoints = []
            self.current_path = None
            self.play_btn.setEnabled(False)
            self._on_error(str(e))

    # ------------------------------------------------------------- estado
    def _busy(self):
        return self.recorder.running or self.player.running

    def _set_busy_ui(self, recording=False, playing=False):
        self.rec_btn.setEnabled(not recording and not playing)
        self.play_btn.setEnabled(not recording and not playing and bool(self.events))
        self.stop_btn.setEnabled(recording or playing)
        self.macros_list.setEnabled(not recording and not playing)

    # ------------------------------------------------------------ gravar
    def start_record(self):
        if self._busy():
            return
        self.events = []
        self._rec_stopped = False
        self._set_busy_ui(recording=True)
        self.status_lbl.setText("Gravando... (STOP para parar)")
        self._rec_start = time.monotonic()
        self._timer.start()
        hk = self.cfg.get("hotkeys", {})
        ignore_keys = {
            getattr(ecodes, name, None)
            for name in hk.values()
            if getattr(ecodes, name, None) is not None
        }
        self.recorder.start(
            on_error=lambda e: self.bridge.error.emit(str(e)),
            ignore_keys=ignore_keys,
        )
        self._watch_recorder()

    def _watch_recorder(self):
        if self._rec_stopped:
            return
        if self.recorder.running:
            QTimer.singleShot(100, self._watch_recorder)
        elif not self.player.running:
            self._rec_stopped = True
            self.bridge.record_done.emit()

    def _on_record_done(self):
        self._timer.stop()
        self.events = list(self.recorder.events)
        self.start_pos = self.recorder.start_pos
        self.position_checkpoints = list(getattr(self.recorder, "position_log", []))
        self._set_busy_ui()
        n_chk = len(self.position_checkpoints)
        chk = f" +{n_chk} checkpoints" if n_chk else ""
        self.status_lbl.setText(f"{len(self.events)} eventos gravados{chk}")
        if self.events:
            self._save_dialog()

    def _save_dialog(self):
        # _in_dialog DENTRO do try pra garantir que o finally sempre resete
        try:
            self._in_dialog = True
            # Traz a janela para frente (essencial quando parou via hotkey
            # e a janela está atrás do jogo/app)
            self.raise_()
            self.activateWindow()
            name, ok = QInputDialog.getText(
                self, "Salvar macro", "Nome:", QLineEdit.Normal,
                f"macro_{int(time.time())}",
            )
        finally:
            self._in_dialog = False
        if not ok or not name.strip():
            self.status_lbl.setText("Gravação descartada (não salva)")
            return
        path = os.path.join(self.cfg["macros_dir"], f"{name.strip()}.json")
        try:
            storage.save(self.events, path, name.strip(),
                         start_pos=self.start_pos,
                         position_log=self.position_checkpoints)
            self.current_path = path
            self._refresh_macros()
            self._select_macro_by_path(path)
            self.status_lbl.setText(f"Salvo: {name.strip()}.json")
        except (storage.MacroError, OSError) as e:
            self._on_error(str(e))

    def _select_macro_by_path(self, path):
        """Seleciona o item na lista cujo data(UserRole) == path."""
        for i in range(self.macros_list.count()):
            item = self.macros_list.item(i)
            if item.data(Qt.UserRole) == path:
                self.macros_list.setCurrentItem(item)
                break

    # ----------------------------------------------------------- playback
    def start_play(self):
        if self._busy() or not self.events:
            return
        self._set_busy_ui(playing=True)
        loop = self.cfg["loop_count"]
        self.status_lbl.setText("Reproduzindo " + ("∞" if loop <= 0 else f"{loop}×") + "...")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.loop_lbl.setVisible(True)
        self.loop_lbl.setText("Iniciando...")
        self.player.play(
            self.events,
            speed=self.cfg["speed"],
            loop=loop,
            start_pos=self.start_pos,
            position_checkpoints=self.position_checkpoints,
            on_done=lambda: self.bridge.play_done.emit(),
            on_error=lambda e: self.bridge.error.emit(str(e)),
            on_progress=lambda *a: self.bridge.play_progress.emit(*a),
        )

    def _on_play_progress(self, elapsed, duration, cur_loop, total_loops):
        if duration > 0:
            pct = min(elapsed / duration, 1.0)
            self.progress_bar.setValue(int(pct * 1000))
            self.timer_lbl.setText(f"{fmt_time(elapsed)} / {fmt_time(duration)}")
            self.progress_bar.setFormat(f"{pct * 100:.0f}%")
        if total_loops <= 0:
            self.loop_lbl.setText(f"▶ Loop {cur_loop}  (∞)")
        else:
            self.loop_lbl.setText(f"▶ Loop {cur_loop} / {total_loops}")

    def _on_play_done(self):
        self._set_busy_ui()
        self.progress_bar.setValue(1000)
        self.progress_bar.setFormat("100%")
        self.timer_lbl.setText("00:00.000")
        self.status_lbl.setText("Pronto")
        QTimer.singleShot(2000, self._hide_progress)

    # --------------------------------------------------------------- stop
    def stop_all(self):
        was_recording = self.recorder.running
        self.recorder.stop()
        self.player.stop()
        if was_recording:
            self._rec_stopped = True
            self.bridge.record_done.emit()

    def _tick(self):
        self.timer_lbl.setText(fmt_time(time.monotonic() - self._rec_start))

    def _hide_progress(self):
        if not self.player.running:
            self.progress_bar.setVisible(False)
            self.loop_lbl.setVisible(False)

    # ------------------------------------------------------ import/export
    def import_macro(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar macro", self.cfg["last_dir"], "Macros (*.json)"
        )
        if not path:
            return
        self.cfg["last_dir"] = os.path.dirname(path)
        cfg_mod.save(self.cfg)
        try:
            dst = storage.import_macro(path, self.cfg["macros_dir"])
            self._refresh_macros()
            self.status_lbl.setText(f"Importado: {os.path.basename(dst)}")
        except storage.MacroError as e:
            self._on_error(str(e))

    def export_macro(self):
        src = self._selected_path()
        if not src:
            self.status_lbl.setText("Selecione uma macro para exportar")
            return
        default = os.path.join(self.cfg["last_dir"], os.path.basename(src))
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar macro", default, "Macros (*.json)"
        )
        if not path:
            return
        self.cfg["last_dir"] = os.path.dirname(path)
        cfg_mod.save(self.cfg)
        try:
            dst = storage.export(src, path)
            self.status_lbl.setText(f"Exportado: {dst}")
        except storage.MacroError as e:
            self._on_error(str(e))

    def delete_macro(self):
        src = self._selected_path()
        if not src:
            return
        if QMessageBox.question(
            self, "Apagar", f"Apagar '{os.path.basename(src)}'?"
        ) != QMessageBox.Yes:
            return
        try:
            os.remove(src)
        except OSError as e:
            self._on_error(str(e))
            return
        if self.current_path == src:
            self.events = []
            self.current_path = None
            self.play_btn.setEnabled(False)
        self._refresh_macros()
        self.status_lbl.setText("Macro apagada")

    # ------------------------------------------------------------- config
    def open_config(self):
        try:
            self._in_dialog = True
            dlg = ConfigDialog(self.cfg, self)
            if dlg.exec() == QDialog.Accepted:
                self.cfg = dlg.result_config()
                cfg_mod.save(self.cfg)
                self._refresh_buttons()
                self._refresh_macros()
                self._restart_hotkeys()
                self.status_lbl.setText("Configurações salvas")
        finally:
            self._in_dialog = False

    # ------------------------------------------------------------ hotkeys
    def _start_hotkeys(self):
        hk = self.cfg["hotkeys"]
        bindings = {
            "record": (hk["record"], lambda: self.bridge.hotkey.emit("record")),
            "play": (hk["play"], lambda: self.bridge.hotkey.emit("play")),
            "stop": (hk["stop"], lambda: self.bridge.hotkey.emit("stop")),
        }
        self.hotkeys = HotkeyListener(bindings)
        try:
            self.hotkeys.start()
        except Exception:  # noqa: BLE001 - hotkeys são opcionais
            pass

    def _restart_hotkeys(self):
        self.hotkeys.stop()
        self._start_hotkeys()

    def _on_hotkey(self, action):
        if self._in_dialog:
            return
        if action == "record":
            if self._busy():
                self.status_lbl.setText("Já está gravando ou reproduzindo")
            else:
                self.start_record()
        elif action == "play":
            if self._busy():
                self.status_lbl.setText("Já está gravando ou reproduzindo")
            elif not self.events:
                self.status_lbl.setText("Nenhuma macro carregada")
            else:
                self.start_play()
        elif action == "stop":
            self.stop_all()

    # -------------------------------------------------------------- erros
    def _on_error(self, msg):
        self._timer.stop()
        self._set_busy_ui()
        QMessageBox.critical(self, "Erro", msg)
        self.status_lbl.setText("Erro")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.stop_all()
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.recorder.stop()
        self.player.stop()
        self.hotkeys.stop()
        super().closeEvent(event)


class ConfigDialog(QDialog):
    """Configurações: hotkeys e pasta de macros."""

    _HOTKEY_CHOICES = (
        [f"KEY_F{i}" for i in range(1, 25)]
        + ["KEY_ESC", "KEY_PAUSE", "KEY_INSERT", "KEY_HOME", "KEY_END",
           "KEY_PAGEUP", "KEY_PAGEDOWN", "KEY_DELETE", "KEY_BACKSPACE",
           "KEY_TAB", "KEY_CAPSLOCK", "KEY_SPACE", "KEY_ENTER", "KEY_GRAVE",
           "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT",
           "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT",
           "KEY_LEFTCTRL", "KEY_RIGHTCTRL",
           "KEY_LEFTALT", "KEY_RIGHTALT",
           "KEY_LEFTMETA", "KEY_RIGHTMETA",
           "KEY_COMPOSE", "KEY_MENU"]
        + [f"KEY_{i}" for i in range(10)]
        + [f"KEY_{chr(c)}" for c in range(ord("A"), ord("Z") + 1)]
    )

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setStyleSheet(STYLESHEET)
        self._cfg = dict(cfg)
        self._cfg["hotkeys"] = dict(cfg["hotkeys"])

        form = QFormLayout(self)

        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(cfg["macros_dir"])
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(browse)
        form.addRow("Pasta macros", dir_row)

        self.hk = {}
        for action, label in (("record", "Hotkey gravar"),
                              ("play", "Hotkey play"),
                              ("stop", "Hotkey stop")):
            combo = QComboBox()
            combo.addItems(self._HOTKEY_CHOICES)
            cur = cfg["hotkeys"][action]
            if cur not in self._HOTKEY_CHOICES:
                combo.addItem(cur)
            combo.setCurrentText(cur)
            self.hk[action] = combo
            form.addRow(label, combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta de macros", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def result_config(self):
        self._cfg["macros_dir"] = self.dir_edit.text() or self._cfg["macros_dir"]
        for action, combo in self.hk.items():
            self._cfg["hotkeys"][action] = combo.currentText()
        return self._cfg


def main():
    app = QApplication.instance() or QApplication([])
    win = MacroRecorderUI()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
