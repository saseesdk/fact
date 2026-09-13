# Fact Check — desktop hotkey tool (issue #19)

A standalone background utility so fact-checking works **outside the
browser too** — Word, Notepad, a PDF reader, email, anywhere you can
select text. The Chrome extension can't do this itself: extension APIs
only ever see inside the browser, there's no way for one to reach into
another application's window. This is a second, separate program that
can, sharing the exact same backend (`src/app.py`) the extension and web
UI already use — no duplicated verification logic, just a third front
door into the same pipeline.

## Setup

1. Start the backend first (same as for the extension/web UI):
   ```
   cd D:\PROGRAMMING\fact
   venv\Scripts\python src\app.py
   ```
2. Install this tool's own (much lighter) dependencies — separate venv
   recommended, since this never needs torch/transformers/spacy:
   ```
   cd desktop
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```
3. Run it:
   ```
   venv\Scripts\python hotkey_tool.py
   ```
   A tray icon appears (bottom-right, near the clock). Leave it running.

## Usage

Select text in **any** application — Word, Notepad, a PDF viewer, a
browser, an email — then press **Ctrl+Alt+F**. A small popup appears in
the top-right of the screen: a "checking claim N of total" progress
message while it works, then each claim's verdict (color-coded, same
categories as the extension: supported / misrepresented / unsupported),
with its source where one was found.

If the hotkey doesn't fire for some reason, right-click the tray icon and
choose "Check clipboard/selection now" as a fallback.

## How it works

There's no Windows API for "get whatever text is currently selected in
any application" — but there is a universal one almost every app honors:
Ctrl+C. On hotkey press, `grab_selected_text()` simulates Ctrl+C, waits
briefly, reads the clipboard, and restores whatever was on the clipboard
before (so this doesn't clobber something you'd already copied). That
text goes through the same two calls the browser extension makes —
`POST /api/segregate` then `POST /api/verify` per claim — reported via a
Tk popup built fresh each time, driven off `on_hotkey()`'s callback (which
`keyboard` runs on its own worker thread per hotkey press, so it can
safely block on the network calls) instead of Tkinter's own main thread
directly — a Tkinter window may only ever be touched from the thread
running its own `mainloop()`, so cross-thread communication goes through a
plain `queue.Queue`, drained by a repeating `root.after(...)` poll.

## Packaging as a single .exe

So people can just download and run one file, with no Python install of
their own:

```
venv\Scripts\pyinstaller --onefile --windowed --name "FactCheckHotkey" hotkey_tool.py
```

The `.exe` lands in `desktop/dist/`. `--windowed` suppresses the console
window (the tray icon is the only visible UI). Note the packaged `.exe`
still needs the backend (`src/app.py`) reachable at `127.0.0.1:5000` —
it's a front end, not a bundled copy of the NLI models.

## Known limitations

- **Windows only** — `keyboard`'s global hotkey hook and the Ctrl+C
  simulation are Windows-specific in how they're used here (this whole
  repo targets Windows so far; see the root `README.md`).
- **Won't intercept keys in an elevated (Run as Administrator) window**
  unless this tool is also run elevated — a non-admin keyboard hook can't
  reach into an admin-elevated process. Uncommon for normal Word/Notepad/
  PDF-reader usage, but worth knowing.
- Same backend-must-be-running requirement as the extension — this talks
  to `127.0.0.1:5000`, nothing hosted/deployed.
- No settings UI yet for changing the hotkey — it's the `HOTKEY` constant
  at the top of `hotkey_tool.py`.
