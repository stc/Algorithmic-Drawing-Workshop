import os
import sys
import time
import threading
import shutil
import uuid
from flask import Flask, render_template, request, jsonify
from main import AutoPen, convert_svg_to_gcode_vpype, execute_raw_gcode_from_file

app = Flask(__name__)

# --- globals ---
pen = None
pen_lock = threading.Lock()
plot_thread = None
plot_event = threading.Event()       # set = running, cleared = paused
stop_event = threading.Event()       # set = stop requested
is_plotting = False
plotting_lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

REMEMBER_PEN_HEIGHT = 9  # height to lower pen to when drawing

# ----------------------------------------------------------------
#  helpers
# ----------------------------------------------------------------

def _get_pen():
    global pen, pen_lock
    with pen_lock:
        return pen


def _set_pen(p):
    global pen, pen_lock
    with pen_lock:
        pen = p


def _plot_worker(svg_path, offset_x, offset_y, gcode_profile):
    global is_plotting, pen, plot_event, stop_event

    try:
        p = _get_pen()
        if p is None:
            return

        gcode_path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}.gcode")
        convert_svg_to_gcode_vpype(svg_path, gcode_path, profile=gcode_profile)

        commands = []
        with open(gcode_path, 'r') as f:
            for line in f:
                cmd = line.strip().split(";")[0]
                if cmd:
                    commands.append(cmd)

        # Ensure pen is up before traveling to offset
        p.set_pen_height(0)
        # move to offset position first (pen up)
        if offset_x != 0 or offset_y != 0:
            p.move_xy_constant_speed(offset_x, offset_y)

        for cmd in commands:
            if stop_event.is_set():
                break

            # wait while paused
            while not plot_event.is_set():
                if stop_event.is_set():
                    break
                time.sleep(0.05)

            if stop_event.is_set():
                break

            p.send_gcode(cmd, cancel_event=stop_event)

    except Exception as e:
        print(f"Plot worker error: {e}", file=sys.stderr)
    finally:
        p = _get_pen()
        if p is not None:
            with p.state_lock:
                p.is_paused = False
        with plotting_lock:
            is_plotting = False
        stop_event.clear()
        plot_event.set()  # reset to "running" state


# ----------------------------------------------------------------
#  flask routes
# ----------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    p = _get_pen()
    with plotting_lock:
        plotting = is_plotting
    
    pen_state = "—"
    if p is not None:
        with p.state_lock:
            pen_state = "up" if p.current_z == 0 else "down"

    return jsonify({
        "connected": p is not None,
        "plotting": plotting,
        "paused": plotting and not plot_event.is_set(),
        "stop_requested": stop_event.is_set(),
        "pen": pen_state,
    })


@app.route("/api/connect", methods=["POST"])
def api_connect():
    global pen
    if _get_pen() is not None:
        return jsonify({"ok": False, "error": "Already connected"}), 400

    data = request.get_json(silent=True) or {}
    device = data.get("device")
    speed = min(data.get("speed", 2500), 2500)

    try:
        p = AutoPen(device_location=device, default_speed=speed)
        _set_pen(p)
        return jsonify({"ok": True})
    except Exception as e:
        print("SERIAL ERROR:", repr(e))
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    if is_plotting:
        return jsonify({"ok": False, "error": "Stop plotting first"}), 400

    p.close()
    _set_pen(None)
    return jsonify({"ok": True})


@app.route("/api/pen-up", methods=["POST"])
def api_pen_up():
    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400
    try:
        p.set_pen_height(0)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "pen": "up"})


@app.route("/api/pen-down", methods=["POST"])
def api_pen_down():
    global REMEMBER_PEN_HEIGHT
    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400
    
    data = request.get_json(silent=True) or {}
    height = data.get("height", REMEMBER_PEN_HEIGHT)
    try:
        height = float(height)
        if not (0 <= height <= 9):
            return jsonify({"ok": False, "error": "Height must be between 0 and 9"}), 400
        REMEMBER_PEN_HEIGHT = height
        p.set_pen_height(height)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid height"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "pen": "down"})


@app.route("/api/start", methods=["POST"])
def api_start():
    global is_plotting, plot_thread, plot_event, stop_event

    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    data = request.get_json(silent=True) or {}
    svg_content = data.get("svg")
    offset_x = data.get("offset_x", 0)
    offset_y = data.get("offset_y", 0)
    gcode_profile = data.get("gcode_profile", "idrawv2")
    if gcode_profile not in {"idrawv2", "bachin"}:
        return jsonify({"ok": False, "error": "Invalid machine profile"}), 400
    if not svg_content:
        return jsonify({"ok": False, "error": "No SVG content"}), 400

    with plotting_lock:
        if is_plotting:
            return jsonify({"ok": False, "error": "Already plotting"}), 400
        is_plotting = True

    svg_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}.svg")
    with open(svg_path, 'w') as f:
        f.write(svg_content)

    plot_event.set()
    stop_event.clear()

    plot_thread = threading.Thread(
        target=_plot_worker,
        args=(svg_path, offset_x, offset_y, gcode_profile),
        daemon=True,
    )
    plot_thread.start()

    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global is_plotting, pen

    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    with plotting_lock:
        if not is_plotting:
            return jsonify({"ok": True, "message": "Not plotting"})

    stop_event.set()
    plot_event.set()  # unblock in case paused
    try:
        p.set_pen_height(0)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True})


@app.route("/api/pause", methods=["POST"])
def api_pause():
    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    with plotting_lock:
        if not is_plotting:
            return jsonify({"ok": False, "error": "Not plotting"}), 400

    if not plot_event.is_set():
        return jsonify({"ok": True, "message": "Already paused"})

    plot_event.clear()
    try:
        p.pause()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "pen": "up"})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    with plotting_lock:
        if not is_plotting:
            return jsonify({"ok": False, "error": "Not plotting"}), 400

    if plot_event.is_set():
        return jsonify({"ok": True, "message": "Not paused"})

    try:
        p.resume()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    plot_event.set()
    return jsonify({"ok": True, "pen": "down"})


@app.route("/api/move", methods=["POST"])
def api_move():
    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    data = request.get_json(silent=True) or {}
    x = data.get("x", 0)
    y = data.get("y", 0)
    speed = data.get("speed")

    try:
        is_homing = (float(x) == 0.0 and float(y) == 0.0)
        
        if is_homing:
            p.set_absolute_coordinate_mode()
            if speed:
                p.move_xy_variable_speed(0.0, 0.0, float(speed), update_current_speed=False)
            else:
                p.move_xy_constant_speed(0.0, 0.0)
        else:
            with p.state_lock:
                was_absolute = p.is_absolute_coordinate_mode
            
            if was_absolute:
                p.set_relative_coordinate_mode()
                
            if speed:
                p.move_xy_variable_speed(float(x), float(y), float(speed), update_current_speed=False)
            else:
                p.move_xy_constant_speed(float(x), float(y))
                
            if was_absolute:
                p.set_absolute_coordinate_mode()
                
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/home", methods=["POST"])
def api_home():
    p = _get_pen()
    if p is None:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    with plotting_lock:
        if is_plotting:
            return jsonify({"ok": False, "error": "Stop plotting first"}), 400

    data = request.get_json(silent=True) or {}
    profile = data.get("gcode_profile", "idrawv2")
    try:
        p.set_pen_height(0)
        p.set_absolute_coordinate_mode()
        if profile == "bachin":
            p.home_hardware()
        elif profile == "idrawv2":
            p.move_xy_constant_speed(0.0, 0.0)
        else:
            return jsonify({"ok": False, "error": "Invalid machine profile"}), 400
        return jsonify({"ok": True, "pen": "up"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----------------------------------------------------------------
#  entry point
# ----------------------------------------------------------------

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print(f"Starting PlotPy-Control Web UI at http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
