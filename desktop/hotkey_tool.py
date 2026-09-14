"""Standalone desktop fact-check tool (issue #19: works outside the browser).

Select text in any Windows application, press Shift+F9, get a verdict for
each checkable claim in a sliding toast at the bottom-right of the screen.
Reuses the same Flask backend (src/app.py) the browser extension and web UI
call - /api/segregate then /api/verify per claim - so there's no duplicated
verification logic, just a new front door.

Run src/app.py first (this only calls it over HTTP, doesn't start it).
"""

import html
import socket
import sys
import time

import keyboard
import pyperclip
import requests
from PySide6.QtCore import Qt, QObject, Signal, QPropertyAnimation, QEasingCurve, QTimer, QPoint, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsOpacityEffect, QSystemTrayIcon, QMenu,
)

BACKEND = "http://127.0.0.1:5000"
HOTKEY = "shift+f9"
DEBOUNCE_SECONDS = 0.5
CLIPBOARD_WAIT_SECONDS = 0.2
MAX_CLAIMS_SHOWN = 4

MARGIN = 20
WIDTH = 360
SLIDE_MS = 350
HOLD_MS = 20000

_SINGLE_INSTANCE_PORT = 51987
_singleton_socket = None

VERDICT_COLORS = {
    "supported": "#3fb950",
    "misrepresented": "#e3b341",
    "unsupported": "#8b949e",
    "outdated": "#58a6ff",
    "error": "#f85149",
}


def _acquire_single_instance_lock():
    global _singleton_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _SINGLE_INSTANCE_PORT))
    except OSError:
        s.close()
        return False
    _singleton_socket = s
    return True


def _escape(text):
    return html.escape(str(text))


class Toast(QWidget):
    """A single sliding card. Content can be replaced in place while it's
    showing (used to turn a "Checking..." toast into the real result)."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(
            """
            QWidget#card { background-color: rgba(32, 32, 36, 235); border-radius: 12px; }
            QLabel { color: white; background: transparent; }
            QLabel#title { font-size: 13px; font-weight: 600; color: #c9d1d9; }
            QLabel#body { font-size: 12px; }
            QPushButton#closeBtn {
                color: #8b949e; background: transparent; border: none; font-size: 13px;
            }
            QPushButton#closeBtn:hover { color: white; }
            """
        )
        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._layout = QVBoxLayout(self._card)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("Fact Check")
        self._title.setObjectName("title")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._dismiss)
        header.addWidget(self._title, 1)
        header.addWidget(close_btn, 0)
        self._layout.addLayout(header)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.0)

        self._body_labels = []
        self._dismiss_timer = None
        self._anims = []
        self._dismissing = False

    def _clear_body(self):
        for lbl in self._body_labels:
            self._layout.removeWidget(lbl)
            lbl.deleteLater()
        self._body_labels = []

    def set_html_lines(self, title, lines):
        self._title.setText(title)
        self._clear_body()
        for line in lines:
            lbl = QLabel(line)
            lbl.setObjectName("body")
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.RichText)
            self._layout.addWidget(lbl)
            self._body_labels.append(lbl)
        # Deferred to the next event-loop tick: measuring sizeHint() in the
        # same call that just added/removed labels sometimes returned a
        # stale (too-short) height for wrapped rich-text content - the card
        # then got positioned/sized for the OLD height and the new, taller
        # content hung off the bottom of the screen instead of being fully
        # visible. Giving Qt one tick to finish laying out the new labels
        # before we measure fixes it.
        QTimer.singleShot(0, self._apply_size_and_position)

    def _apply_size_and_position(self):
        self._card.adjustSize()
        height = self._card.sizeHint().height()
        self._card.setFixedSize(WIDTH, height)
        self.setFixedSize(WIDTH, height)

        screen = QApplication.primaryScreen().availableGeometry()
        end_pos = QPoint(screen.width() - WIDTH - MARGIN, screen.height() - height - MARGIN)
        self._end_pos = end_pos
        if not self.isVisible():
            self._start_pos = QPoint(end_pos.x(), screen.height())
            self.move(self._start_pos)
            self._slide_in_now()
        else:
            # already on screen and growing/shrinking - just keep it pinned
            # to the same bottom-right anchor instead of re-sliding.
            self.move(end_pos)

    def _slide_in_now(self):
        self.show()
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(SLIDE_MS)
        slide.setStartValue(self._start_pos)
        slide.setEndValue(self._end_pos)
        slide.setEasingCurve(QEasingCurve.OutCubic)
        fade = QPropertyAnimation(self._opacity, b"opacity", self)
        fade.setDuration(SLIDE_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        slide.start()
        fade.start()
        self._anims = [slide, fade]
        # No auto-dismiss timer started here - callers decide: a
        # "checking..." state stays up indefinitely (stop_dismiss_timer),
        # a final result/message starts the 20s countdown (_restart_dismiss_timer).

    def stop_dismiss_timer(self):
        self._dismissing = False
        if self._dismiss_timer is not None:
            self._dismiss_timer.stop()

    def _restart_dismiss_timer(self):
        self._dismissing = False
        if self._dismiss_timer is not None:
            self._dismiss_timer.stop()
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._dismiss)
        self._dismiss_timer.start(HOLD_MS)

    def _dismiss(self):
        if self._dismissing:
            return
        self._dismissing = True
        if self._dismiss_timer is not None:
            self._dismiss_timer.stop()

        screen = QApplication.primaryScreen().availableGeometry()
        out_pos = QPoint(self._end_pos.x(), screen.height())
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(SLIDE_MS)
        slide.setStartValue(self.pos())
        slide.setEndValue(out_pos)
        slide.setEasingCurve(QEasingCurve.InCubic)
        slide.finished.connect(self.close)
        slide.start()
        self._anims = [slide]


class Bridge(QObject):
    show_loading = Signal(str)
    show_result = Signal(list, str)
    show_message = Signal(str)


def _format_claim_line(result):
    verdict = result.get("verdict", "error")
    color = VERDICT_COLORS.get(verdict, "#8b949e")
    sentence = _escape(result.get("claim", ""))
    explanation = _escape(result.get("explanation", ""))
    confidence = result.get("confidence")
    conf_text = f" ({confidence:.0%})" if isinstance(confidence, (int, float)) else ""
    return (
        f'<span style="color:{color}; font-weight:600;">{verdict.upper()}{conf_text}</span> '
        f'&mdash; {sentence}<br>'
        f'<span style="color:#8b949e; font-size:11px;">{explanation}</span>'
    )


def check_text(text, bridge):
    try:
        resp = requests.post(f"{BACKEND}/api/segregate", json={"text": text}, timeout=15)
        resp.raise_for_status()
        claims = resp.json().get("claims", [])
    except requests.exceptions.ConnectionError:
        bridge.show_message.emit("Backend not running - start src/app.py first.")
        return
    except Exception as e:
        bridge.show_message.emit(f"Error reaching backend: {e}")
        return

    if not claims:
        bridge.show_message.emit("No checkable factual claims found in the selection.")
        return

    lines = []
    for entry in claims[:MAX_CLAIMS_SHOWN]:
        sentence = entry["sentence"]
        try:
            vresp = requests.post(f"{BACKEND}/api/verify", json={"claim": sentence}, timeout=60)
            vresp.raise_for_status()
            result = vresp.json()
        except Exception as e:
            result = {"claim": sentence, "verdict": "error", "explanation": str(e)}
        lines.append(_format_claim_line(result))

    remaining = len(claims) - MAX_CLAIMS_SHOWN
    title = f"{len(claims)} claim{'s' if len(claims) != 1 else ''} checked"
    if remaining > 0:
        lines.append(f'<span style="color:#8b949e; font-size:11px;">+{remaining} more not shown</span>')

    bridge.show_result.emit(lines, title)


def grab_selected_text():
    previous_clipboard = ""
    try:
        previous_clipboard = pyperclip.paste()
    except Exception:
        pass

    keyboard.send("ctrl+c")
    time.sleep(CLIPBOARD_WAIT_SECONDS)

    try:
        current = pyperclip.paste()
    except Exception:
        current = ""

    if current and current != previous_clipboard:
        try:
            pyperclip.copy(previous_clipboard)
        except Exception:
            pass
        return current
    return None


def _tray_icon_pixmap():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#3fb950"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 60, 60)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(28)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "F")
    painter.end()
    return pixmap


def main():
    if not _acquire_single_instance_lock():
        print("Fact Check hotkey tool is already running.")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    bridge = Bridge()
    current_toast = {"widget": None}

    def _get_toast():
        widget = current_toast["widget"]
        if widget is None or not widget.isVisible():
            widget = Toast()
            current_toast["widget"] = widget
        return widget

    def on_show_loading(text):
        toast = _get_toast()
        toast.set_html_lines("Fact Check", [f'<span style="color:#8b949e;">{_escape(text)}</span>'])
        # "Checking..." stays up no matter how long the backend takes -
        # only a real result or message starts the auto-dismiss countdown.
        toast.stop_dismiss_timer()

    def on_show_result(lines, title):
        toast = _get_toast()
        toast.set_html_lines(title, lines)
        toast._restart_dismiss_timer()

    def on_show_message(text):
        on_show_result([f'<span style="color:#8b949e;">{_escape(text)}</span>'], "Fact Check")

    bridge.show_loading.connect(on_show_loading)
    bridge.show_result.connect(on_show_result)
    bridge.show_message.connect(on_show_message)

    last_trigger = [0.0]

    def on_hotkey(_event):
        # Runs on keyboard's own listener thread. Clipboard grab and the
        # blocking HTTP calls happen here; only bridge.emit() touches Qt.
        now = time.monotonic()
        if now - last_trigger[0] < DEBOUNCE_SECONDS:
            return
        last_trigger[0] = now

        # Show something immediately, no matter what - the popup firing on
        # every press is mandatory, independent of how long the backend
        # call ends up taking.
        bridge.show_loading.emit("Checking selected text...")

        text = grab_selected_text()
        if not text:
            bridge.show_message.emit("Nothing new selected - select text, then press Shift+F9.")
            return
        check_text(text, bridge)

    # on_press_key fires on the F9 keycode itself, regardless of what other
    # modifiers keyboard's own state-tracking currently believes are held -
    # add_hotkey's exact-combo matching proved unreliable on this machine
    # (same failure mode we already hit with bare F9). On this hardware,
    # bare F9 alone never reaches the hook at all (intercepted by the
    # laptop's Fn-row driver), so in practice this only ever fires when the
    # user is holding Shift too - i.e. Shift+F9.
    keyboard.on_press_key("f9", on_hotkey, suppress=False)

    tray = QSystemTrayIcon(QIcon(_tray_icon_pixmap()), app)
    tray.setToolTip("Fact Check (Shift+F9)")
    menu = QMenu()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.show()

    print(f"Fact Check hotkey tool running. Select text anywhere, press {HOTKEY}.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
