# Interactive Plotter

Flask web control for the iDraw/PyPlot serial plotter. Draw directly on the bed preview with a mouse, trackpad, or touch screen. Browser coordinates are mapped to millimetres; the screen's top edge maps to the plotter's maximum Y and the bottom edge maps to Y=0. The pen stays up while positioning at the start of a stroke and lowers only when the pointer moves to create a line.

## Run

From this directory:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://<raspberry-pi-ip>:5002` from another device, or
`http://127.0.0.1:5002` on the Pi itself. Set the serial device before
connecting. The default bed is 700 x 1000 mm; change `BED_WIDTH_MM` and
`BED_HEIGHT_MM` in `app.py` for another machine.

The Connection panel lists attached USB serial devices. Click **Refresh**
after plugging in the plotter, then select it before connecting.

Use **Pen down** and **Pen up** in the Safety panel to set the pen height
manually.

For an SSH tunnel, run `ssh -L 5002:localhost:5002 <user>@<raspberry-pi-ip>`
and then open `http://127.0.0.1:5002` locally.

Restart `python app.py` after updating the project so the `/api/home` route is loaded.

The project imports `AutoPen` from `Tools/PyPlot-Control/main.py`, so it uses the same 115200-baud G-code protocol and pen-height convention as PyPlot-Control. Each pointer movement is sent in order, and the pen is lifted on pointer release, cancellation, browser blur, disconnect, Home, and server shutdown. Home forces absolute positioning and moves to `X0 Y0` with the pen up.
