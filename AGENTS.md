# Agent instructions

## Repository layout

- `PyPlot-Control/` is the main Flask UI for SVG-to-G-code plotting; `app.py` owns the API/UI and `main.py` owns the shared 115200-baud serial protocol and vpype conversion.
- `Interactive-Control/` is a separate Flask UI for direct drawing; it imports `AutoPen` from `../PyPlot-Control/main.py` rather than maintaining its own serial implementation.
- `PyPlot-Control/uploads/` and `PyPlot-Control/temp/` are runtime output directories and are ignored; do not commit generated SVG/G-code files.

## Setup and run

- Each app has its own `requirements.txt`; create/activate a virtual environment inside the app directory before installing it (`python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`).
- Run commands from the app's own directory: `PyPlot-Control/main.py` invokes `vpype-settings.toml` by relative path, and `Interactive-Control/app.py` resolves the shared module from the sibling directory.
- PyPlot-Control's executable default is port `3000` (`python app.py [port]`) and binds to `0.0.0.0`, so remote clients use the Pi's LAN address; its README's `5001`/localhost example is stale.
- Interactive-Control's executable default is port `5002` and currently binds only to `127.0.0.1` (`python app.py [port]`).
- Plotting requires the `vpype` executable on `PATH` and a connected serial plotter; `AutoPen` defaults to `/dev/ttyACM0` on Linux and `/dev/cu.usbmodem201912341` on macOS unless a device is supplied.

## Verification

- There is no configured test, lint, or typecheck suite; for Python-only changes run `python3 -m py_compile app.py` from each affected app directory and `git diff --check`.
- Hardware changes should be verified with the real plotter only after checking the selected serial device, pen-up state, and machine profile; API calls send movement/G-code directly to the device.

## Change boundaries

- Preserve the shared `AutoPen` protocol when changing either UI; changes to `PyPlot-Control/main.py` affect both applications.
- Keep machine-specific coordinate behavior in the selected profile (`idrawv2` vs `bachin`) and do not assume both UIs use the same bed dimensions or coordinate origin.
