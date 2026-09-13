"""Fact Check — desktop hotkey tool (issue #19: "the app should work
everywhere", not just the browser).

A Chrome extension can only ever see inside the browser itself — there is
no extension API that reaches into Word, Notepad, a PDF reader, or any
other application. Getting the same "select text, get a verdict" behavior
everywhere else needs a separate, OS-level background program instead.
That's what this is.

Deliberately isolated from the rest of this repo: this only talks to
src/app.py over plain HTTP (the same POST /api/segregate and
POST /api/verify calls the browser extension and web UI already use) — it
never imports any of the NLI/retrieval code directly, so running this
never needs torch/transformers/spacy installed, just the light
dependencies in requirements.txt. Backend and this tool can even live on
different machines on the same network with no code change here.

Requires the backend already running:
    venv\\Scripts\\python src\\app.py

Usage: run this script (or the packaged .exe — see README.md). It sits
quietly in the system tray. Select text in any application — Word,
Notepad, a PDF reader, a browser, anywhere — press the hotkey (default
Ctrl+Alt+F), and a small popup near the corner of the screen shows the
verdict for each checkable claim found in the selection.
"""

import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

import keyboard
import pyperclip
import pystray
import requests
from PIL import Image, ImageDraw

API_BASE = "http://127.0.0.1:5000"
HOTKEY = "ctrl+alt+f"

# How long to wait after simulating Ctrl+C before reading the clipboard.
# Ctrl+C isn't instant — the target application needs a moment to actually
# populate the clipboard before we read it back. Confirmed directly that
# reading immediately after keyboard.send() sometimes still returns the
# *previous* clipboard contents, not the freshly selected text.
CLIPBOARD_GRAB_DELAY = 0.15

VERDICT_STYLES = {
    "supported": {"bg": "#dff2e4", "border": "#2f6f4e", "fg": "#1f5238"},
    "misrepresented": {"bg": "#f7dede", "border": "#a13d3d", "fg": "#7a2626"},
    "unsupported": {"bg": "#f1efe5", "border": "#9a8b4f", "fg": "#6b5f30"},
}
DEFAULT_STYLE = {"bg": "#eceae2", "border": "#63695f", "fg": "#1c2321"}

# All communication from the hotkey-listener thread (keyboard runs each
# hotkey callback on its own worker thread, per its own docs, precisely so
# a callback can safely block on network calls) into the Tk GUI thread goes
# through this queue. Tkinter widgets must only ever be touched from the
# thread running mainloop() - polling a queue from a repeating root.after()
# call is the standard safe pattern, rather than calling Tk methods
# directly from the hotkey thread.
event_queue = queue.Queue()

# `keyboard`'s trigger_on_release for a multi-key combo can fire its
# callback more than once for a single physical press+release (confirmed
# directly: one Ctrl+Alt+F triggered on_hotkey twice, and the second,
# overlapping call queued a "loading" event that raced with the first
# call's in-flight "progress" events, updating a popup window the second
# call had already replaced — the destroyed-widget crash seen in testing).
# A simple non-blocking lock makes overlapping triggers a no-op instead of
# two verify runs stepping on each other's popup.
_busy = threading.Lock()


def grab_selected_text():
    """Simulate Ctrl+C to copy whatever is currently selected in the
    foreground application, then read it back from the clipboard, and
    restore whatever was on the clipboard before. This is the only
    OS-agnostic way to reach "the current selection" outside a browser —
    there is no universal "get selected text" API across every Windows
    application, but Ctrl+C is honored almost universally.

    Confirmed directly this needs the hotkey to fire on key RELEASE, not
    press (see add_hotkey(..., trigger_on_release=True) below): if the
    callback runs while Ctrl+Alt+F is still physically held down, sending
    a synthetic "ctrl+c" lands on top of the still-held real Alt key, so
    the target application actually receives Ctrl+Alt+C - not a copy
    shortcut in almost anything - and nothing gets copied at all. Waiting
    for release means the physical keys are already up by the time this
    runs, so the synthetic Ctrl+C is clean.

    Also polls the clipboard for a short window instead of reading once
    after a fixed delay: some applications take longer than others to
    actually populate the clipboard after receiving Ctrl+C."""
    try:
        previous = pyperclip.paste()
    except Exception:
        previous = ""
    keyboard.send("ctrl+c")
    text = previous
    deadline = time.time() + 1.0
    while time.time() < deadline:
        time.sleep(CLIPBOARD_GRAB_DELAY)
        text = pyperclip.paste()
        if text != previous:
            break
    try:
        pyperclip.copy(previous or "")
    except Exception:
        pass
    return text


def verify_text(text, on_progress=None):
    """Same segregate-then-verify-per-claim flow the browser extension
    uses (extension/background.js's verifyTextWithProgress) — one call to
    split the text into checkable claims, then one call per claim, so
    progress can be reported as each one resolves instead of one opaque
    multi-minute wait."""
    seg = requests.post(f"{API_BASE}/api/segregate", json={"text": text}, timeout=30)
    seg.raise_for_status()
    seg_data = seg.json()
    claims = [c["sentence"] for c in seg_data.get("claims", [])]
    skipped = len(seg_data.get("non_claims", []))

    results = []
    total = len(claims)
    if on_progress:
        on_progress(0, total)
    for claim in claims:
        res = requests.post(f"{API_BASE}/api/verify", json={"claim": claim}, timeout=180)
        res.raise_for_status()
        results.append(res.json())
        if on_progress:
            on_progress(len(results), total)
    return results, skipped


def on_hotkey():
    if not _busy.acquire(blocking=False):
        return  # a check is already in flight - ignore the duplicate/extra trigger
    try:
        event_queue.put(("loading", None))
        text = grab_selected_text()
        if not text.strip():
            event_queue.put(("error", "Nothing was selected (or copying it failed)."))
            return
        try:
            results, skipped = verify_text(
                text, on_progress=lambda done, total: event_queue.put(("progress", (done, total)))
            )
            event_queue.put(("result", (results, skipped)))
        except requests.exceptions.RequestException:
            event_queue.put((
                "error",
                "Could not reach the local Fact Check server.\nIs `python src\\app.py` running?",
            ))
    finally:
        _busy.release()


# ---- Tkinter popup (built fresh each time, no window left behind) --------

class ResultPopup:
    def __init__(self, root):
        self.root = root
        self.window = None

    def _window_exists(self):
        # self.window can go stale two ways: the user clicked the popup's
        # own close button, or an error popup auto-destroyed itself after
        # its timeout (see show_error) - either way winfo_exists() is the
        # only reliable way to tell "this Tcl widget still exists" from
        # Python, since the Python object itself doesn't get cleared just
        # because the underlying window was destroyed.
        return self.window is not None and self.window.winfo_exists()

    def _new_window(self):
        if self._window_exists():
            self.window.destroy()
        win = tk.Toplevel(self.root)
        win.title("Fact Check")
        win.attributes("-topmost", True)
        win.configure(bg="#ffffff", highlightbackground="#d7dacd", highlightthickness=1)
        win.geometry("+{}+{}".format(win.winfo_screenwidth() - 380, 40))
        self.window = win
        return win

    def show_loading(self):
        win = self._new_window()
        tk.Label(
            win, text="Finding checkable claims…", bg="#ffffff", fg="#63695f",
            font=("Segoe UI", 10), padx=14, pady=14,
        ).pack()

    def show_progress(self, done, total):
        # A progress update can arrive after the user already closed the
        # popup (or after a prior run's error popup auto-closed) - rather
        # than crash on a destroyed widget, just open a fresh one.
        if not self._window_exists():
            self._new_window()
        for child in self.window.winfo_children():
            child.destroy()
        label = "No checkable claims found yet…" if total == 0 else (
            f"Finished checking {total} claim(s)." if done >= total
            else f"Checking claim {done + 1} of {total}…"
        )
        tk.Label(
            self.window, text=label, bg="#ffffff", fg="#63695f",
            font=("Segoe UI", 10), padx=14, pady=14,
        ).pack()

    def show_error(self, message):
        win = self._new_window()
        tk.Label(
            win, text=f"Failed: {message}", bg="#ffffff", fg="#a13d3d",
            font=("Segoe UI", 10), padx=14, pady=14, wraplength=340, justify="left",
        ).pack()
        win.after(6000, win.destroy)

    def show_result(self, results, skipped):
        win = self._new_window()
        bold = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        header = tk.Frame(win, bg="#ffffff")
        header.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(header, text="Fact Check", bg="#ffffff", font=bold).pack(side="left")
        tk.Button(
            header, text="✕", command=win.destroy, bg="#ffffff", bd=0,
            fg="#63695f", font=("Segoe UI", 11), cursor="hand2",
        ).pack(side="right")

        body = tk.Frame(win, bg="#ffffff")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        if not results:
            tk.Label(
                body, text="No checkable factual claims found in the selection.",
                bg="#ffffff", fg="#63695f", font=("Segoe UI", 9, "italic"), wraplength=340, justify="left",
            ).pack(anchor="w")
        else:
            for r in results:
                style = VERDICT_STYLES.get(r["verdict"], DEFAULT_STYLE)
                card = tk.Frame(body, bg="#ffffff")
                card.pack(fill="x", pady=(0, 8))
                tk.Label(
                    card, text=r["claim"], bg="#ffffff", font=bold,
                    wraplength=340, justify="left", anchor="w",
                ).pack(fill="x")
                verdict_box = tk.Frame(card, bg=style["bg"], highlightbackground=style["border"],
                                        highlightthickness=0, bd=0)
                verdict_box.pack(fill="x", pady=(3, 0))
                tk.Frame(verdict_box, bg=style["border"], width=3).pack(side="left", fill="y")
                inner = tk.Frame(verdict_box, bg=style["bg"])
                inner.pack(side="left", fill="both", expand=True, padx=8, pady=6)
                tk.Label(
                    inner, text=f"{r['verdict'].upper()} ({r['confidence']})",
                    bg=style["bg"], fg=style["fg"], font=("Segoe UI", 8, "bold"),
                ).pack(anchor="w")
                tk.Label(
                    inner, text=r["explanation"], bg=style["bg"], fg=style["fg"],
                    font=("Segoe UI", 9), wraplength=300, justify="left",
                ).pack(anchor="w")
                sources = r.get("sources") or []
                if sources:
                    src_text = ", ".join(s["title"] for s in sources if s.get("title"))
                    tk.Label(
                        inner, text=f"Source: {src_text}", bg=style["bg"], fg=style["fg"],
                        font=("Segoe UI", 8), wraplength=300, justify="left",
                    ).pack(anchor="w", pady=(2, 0))

        if skipped:
            tk.Label(
                body, text=f"{skipped} sentence(s) skipped as opinion/not checkable.",
                bg="#ffffff", fg="#63695f", font=("Segoe UI", 8, "italic"),
            ).pack(anchor="w", pady=(4, 0))


def poll_queue(root, popup):
    try:
        while True:
            action, payload = event_queue.get_nowait()
            if action == "loading":
                popup.show_loading()
            elif action == "progress":
                popup.show_progress(*payload)
            elif action == "result":
                popup.show_result(*payload)
            elif action == "error":
                popup.show_error(payload)
    except queue.Empty:
        pass
    root.after(100, poll_queue, root, popup)


# ---- Tray icon ------------------------------------------------------------

def _make_tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=16, fill=(47, 111, 78, 255))
    d.line([(17, 34), (28, 45), (47, 20)], fill=(255, 255, 255, 255), width=6, joint="curve")
    return img


def run_tray(root):
    def on_check_now(icon, item):
        threading.Thread(target=on_hotkey, daemon=True).start()

    def on_quit(icon, item):
        icon.stop()
        root.after(0, root.quit)

    icon = pystray.Icon(
        "fact_check",
        _make_tray_image(),
        f"Fact Check (hotkey: {HOTKEY})",
        menu=pystray.Menu(
            pystray.MenuItem("Check clipboard/selection now", on_check_now),
            pystray.MenuItem("Quit", on_quit),
        ),
    )
    icon.run()


def main():
    root = tk.Tk()
    root.withdraw()  # no main window — tray icon + on-demand popups only

    popup = ResultPopup(root)
    root.after(100, poll_queue, root, popup)

    # trigger_on_release=True: see grab_selected_text()'s docstring for why
    # firing on press (the default) breaks the Ctrl+C simulation.
    keyboard.add_hotkey(HOTKEY, on_hotkey, trigger_on_release=True)

    tray_thread = threading.Thread(target=run_tray, args=(root,), daemon=True)
    tray_thread.start()

    print(f"Fact Check hotkey tool running. Press {HOTKEY} after selecting text anywhere.")
    root.mainloop()


if __name__ == "__main__":
    main()
