# Desktop hotkey tool

Fact-checks whatever text you have selected in *any* Windows application
(Notepad, Word, a PDF reader, etc.) - not just the browser. Issue #19.

## Setup

```
cd desktop
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

## Run

1. Start the backend from the repo root: `venv\Scripts\python src\app.py`
2. In another terminal: `cd desktop && venv\Scripts\python hotkey_tool.py`
3. Select text anywhere, press **Shift+F9**.

Only one instance runs at a time (a second launch exits immediately) and a
tray icon (green "F") is available to quit.

## What happens on Shift+F9

1. A toast slides in from the bottom-right corner **immediately**, showing
   "Checking selected text..." - this is unconditional, it happens before
   the clipboard is even read.
2. The selected text is grabbed (via a simulated Ctrl+C, clipboard restored
   afterward) and sent through the same pipeline the browser extension uses
   (`/api/segregate` then `/api/verify` per claim).
3. The "Checking..." toast has **no timeout** - it stays up for however long
   verification takes, however long that is.
4. Once a real result (or an error/status message, e.g. "nothing selected"
   or "backend not running") is ready, it replaces the toast's content.
   Each claim is shown with a color-coded verdict (green = supported,
   yellow = misrepresented, gray = unsupported, blue = outdated, red =
   error) and a short explanation.
5. From that point, the toast auto-dismisses after **20 seconds**, or can be
   closed immediately with the **✕** button next to the title.

## Why Shift+F9, not plain F9

The hotkey is registered as a listener on the bare F9 keycode
(`keyboard.on_press_key`), not a `Shift+F9` key-combination match - on at
least one test machine, bare F9 alone never reached the keyboard hook at
all (likely intercepted by the laptop's Fn-row driver for a media/
brightness function), so in practice the only way to generate a real F9
keycode on that hardware was to hold Shift down too. If your F9 key isn't
intercepted like that, plain F9 alone should trigger it as well.
