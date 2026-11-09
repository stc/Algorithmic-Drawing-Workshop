# PyPlot-Control — Web UI for iDraw Pen Plotter

A Flask-based web interface to control an iDraw H A0 or Bachin Draw pen plotter. Provides SVG upload, visual positioning on a virtual A-series bed, and full plot control (start/pause/resume/stop) with pen up/down and manual jogging. Select the machine profile before plotting so the coordinate origin is correct: iDraw uses a bottom-left origin, while Bachin Draw uses a top-left origin.

## How it works

`app.py` is a Flask server that imports `AutoPen` from `iDraw-Control/main.py` for serial communication with the plotter. SVG files are converted to G-code using `vpype` (via `vpype-settings.toml`) and executed line-by-line in a background thread with pause/stop support.

## Quick start

```bash
pip install -r requirements.txt
python app.py [port]
```

Default port is `5001`. Open `http://127.0.0.1:5001` in a browser.

## Features

- **Connect / Disconnect** — serial connection to the plotter device
- **SVG upload** — drag & drop or file picker; auto-converts units to mm for vpype
- **Visual bed** — drag the uploaded SVG to position it on an A0-sized virtual bed; offset X/Y is sent to the plotter
- **Start / Pause / Resume / Stop** — threaded plot execution with pause (pen up) and stop (emergency lift)
- **Pen controls** — pen up/down, configurable pen height (0–9)
- **Manual move** — jog X/Y axes, home to (0,0)
- **Status polling** — live connection, plotting, and pen state

## Dependencies

- Flask — web server
- pyserial — serial communication with the plotter
- vpype + vpype-gcode — SVG to G-code conversion
- tqdm — progress bar for raw G-code execution

## Tips

- Put the pen in the bottom-left corner of the bed before plotting
- vpype converts curves to line segments; run `linemerge` / `linesort` / `reloop` / `linesimplify` in advance for cleaner output
- The pen height range is 0 (up) to 9 (down); default drawing height is set via `REMEMBER_PEN_HEIGHT` in `app.py`
- Offsets are in mm; drag the SVG preview to set them visually
