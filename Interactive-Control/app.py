import atexit
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from serial.tools import list_ports

# Reuse the serial protocol already used by PyPlot-Control.
PYPLOT_DIR = Path(__file__).resolve().parent.parent / "PyPlot-Control"
sys.path.insert(0, str(PYPLOT_DIR))
from main import AutoPen  # noqa: E402


app = Flask(__name__)

BED_WIDTH_MM = 700.0
BED_HEIGHT_MM = 1000.0
PEN_DOWN_HEIGHT = 9.0
DEFAULT_SPEED = 2000.0

pen = None
pen_lock = threading.RLock()
draw_lock = threading.RLock()


@app.errorhandler(404)
def not_found(exc):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": f"API route not found: {request.path}"}), 404
    return exc


@app.errorhandler(500)
def internal_error(exc):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Internal server error"}), 500
    return exc


def get_pen():
    with pen_lock:
        return pen


def clamp(value, low, high):
    return max(low, min(high, float(value)))


def error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@app.get("/")
def index():
    return render_template("index.html", bed_width=BED_WIDTH_MM, bed_height=BED_HEIGHT_MM)


@app.get("/api/status")
def status():
    current = get_pen()
    pen_state = "up"
    if current is not None:
        with current.state_lock:
            pen_state = "down" if current.current_z else "up"
    return jsonify({"connected": current is not None, "pen": pen_state})


@app.get("/api/serial-ports")
def serial_ports():
    """Return the serial devices currently attached to the Raspberry Pi."""
    ports = [
        {
            "device": port.device,
            "description": port.description or "Unknown device",
            "hwid": port.hwid,
        }
        for port in sorted(list_ports.comports(), key=lambda item: item.device)
    ]
    return jsonify({"ports": ports})


@app.post("/api/connect")
def connect():
    global pen
    if get_pen() is not None:
        return error("Already connected")

    data = request.get_json(silent=True) or {}
    device = (data.get("device") or "").strip() or None
    try:
        speed = clamp(data.get("speed", DEFAULT_SPEED), 50, 2500)
        new_pen = AutoPen(device_location=device, default_speed=speed)
    except Exception as exc:
        return error(str(exc), 500)

    with pen_lock:
        pen = new_pen
    return jsonify({"ok": True})


@app.post("/api/disconnect")
def disconnect():
    global pen
    current = get_pen()
    if current is None:
        return error("Not connected")
    try:
        with draw_lock:
            current.set_pen_height(0)
            current.close()
    except Exception as exc:
        return error(str(exc), 500)
    with pen_lock:
        pen = None
    return jsonify({"ok": True})


@app.post("/api/draw")
def draw():
    """Move to one canvas point, changing pen state before the move."""
    current = get_pen()
    if current is None:
        return error("Not connected")

    data = request.get_json(silent=True) or {}
    try:
        x = clamp(data["x"], 0, BED_WIDTH_MM)
        y = clamp(data["y"], 0, BED_HEIGHT_MM)
        pen_down = bool(data.get("pen_down", True))
    except (KeyError, TypeError, ValueError):
        return error("x and y must be numeric")

    try:
        with draw_lock:
            current.set_pen_height(PEN_DOWN_HEIGHT if pen_down else 0)
            current.move_xy_variable_speed(x, y)
    except Exception as exc:
        return error(str(exc), 500)
    return jsonify({"ok": True, "x": x, "y": y, "pen": "down" if pen_down else "up"})


@app.post("/api/pen-up")
def pen_up():
    current = get_pen()
    if current is None:
        return error("Not connected")
    try:
        with draw_lock:
            current.set_pen_height(0)
    except Exception as exc:
        return error(str(exc), 500)
    return jsonify({"ok": True, "pen": "up"})


@app.post("/api/home")
def home():
    current = get_pen()
    if current is None:
        return error("Not connected")
    try:
        with draw_lock:
            current.set_pen_height(0)
            current.set_absolute_coordinate_mode()
            current.move_xy_constant_speed(0, 0)
    except Exception as exc:
        return error(str(exc), 500)
    return jsonify({"ok": True, "pen": "up", "x": 0, "y": 0})


def shutdown():
    current = get_pen()
    if current is not None:
        try:
            with draw_lock:
                current.set_pen_height(0)
                current.close()
        except Exception:
            pass


atexit.register(shutdown)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5002
    # Bind to all interfaces so the UI can be opened using the Raspberry Pi's
    # LAN address (or through an SSH tunnel) from another device.
    print(f"Interactive Plotter at http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
