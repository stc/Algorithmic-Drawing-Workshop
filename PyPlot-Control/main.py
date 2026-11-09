import sys
import threading
import os
import serial
import subprocess
import shutil
import re
from tqdm import tqdm 

class AutoPen():
    def __init__(self, device_location:str=None, default_speed:float=2000):
        if device_location is None:
            if sys.platform.startswith('linux'):
                device_location = '/dev/ttyACM0'  # RPi
            else:
                device_location = '/dev/cu.usbmodem201912341'  # macOS
        
        self.ser = serial.Serial(device_location, 115200, timeout=20)
        self.ser.reset_input_buffer()  # Reset only once during initialization
        self.ser_lock = threading.RLock()
        self.state_lock = threading.RLock()
        self.current_speed = default_speed
        self.default_speed = default_speed
        self.current_z = 0.0
        self.paused_z = 0.0
        self.is_paused = False
        self.is_absolute_coordinate_mode = True

        self.set_speed(self.default_speed)
        self.set_absolute_coordinate_mode()
        self._current_location_as_x0y0()
        self.set_pen_height(0)

    def send_gcode(self, command: str, cancel_event: threading.Event = None) -> None:
        cleaned_cmd = command.strip().split(";")[0].upper()
        import re
        if re.search(r'\bG90\b', cleaned_cmd):
            with self.state_lock:
                self.is_absolute_coordinate_mode = True
        elif re.search(r'\bG91\b', cleaned_cmd):
            with self.state_lock:
                self.is_absolute_coordinate_mode = False

        z_match = re.search(r'[zZ]\s*([0-9.-]+)', cleaned_cmd)
        if z_match:
            try:
                val = float(z_match.group(1))
                with self.state_lock:
                    self.current_z = val
            except ValueError:
                pass

        with self.ser_lock:
            try:
                self.ser.write((command + '\n').encode())
            except serial.SerialException as e:
                print(f"Serial write error: {e}")
                raise e
            while True:
                if cancel_event and cancel_event.is_set():
                    return
                try:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                except serial.SerialException as e:
                    print(f"Serial read error: {e}")
                    break
                if not line:
                    print(f"Serial read timeout waiting for response to command: {command}")
                    break
                if line.lower() == 'ok':
                    break
                if line.lower().startswith('error'):
                    print(f"G-code error: {line} ({command})")
                    break
    
    def close(self) -> None:
        self.ser.close()

    def home_hardware(self) -> None:
        self.set_pen_height(0)
        self.send_gcode("$H")
        self.set_absolute_coordinate_mode()
        self.send_gcode("G92 X0 Y0")

    def pause(self) -> None:
        with self.ser_lock:
            with self.state_lock:
                if self.is_paused:
                    return
                self.is_paused = True
                self.paused_z = self.current_z
            
            self.set_pen_height(0)

    def resume(self) -> None:
        with self.ser_lock:
            with self.state_lock:
                if not self.is_paused:
                    return
                self.is_paused = False
                target_z = self.paused_z    
            # Restore the pen height
            self.set_pen_height(target_z)


    def _current_location_as_x0y0(self) -> None:
        self.send_gcode("G92 X0Y0")

    def set_absolute_coordinate_mode(self) -> None:
        self.send_gcode("G90")
        self.is_absolute_coordinate_mode = True 
    
    def set_relative_coordinate_mode(self) -> None:
        self.send_gcode("G91")
        self.is_absolute_coordinate_mode = False 

    def set_pen_height(self,height:float) -> None:
        assert height >= 0 
        assert height <= 9

        if(self.is_absolute_coordinate_mode):
            self.send_gcode(f"G00 Z{height}")
        else:
            self.set_absolute_coordinate_mode()
            self.send_gcode(f"G00 Z{height}")
            self.set_relative_coordinate_mode()

    def set_speed(self,speed:float) -> None:
        assert speed >= 50 
        assert speed <= 2500
        self.send_gcode(f"F{speed}")

    def move_xy_constant_speed(self,x:float,y:float) -> None:
        self.send_gcode(f"G00 X{x} Y{y}")

    def move_xy_variable_speed(self,x:float,y:float,speed:float=None,update_current_speed:bool=True) -> None:
        # Include a changed feed rate on the movement itself.  This avoids
        # relying on the controller retaining a standalone F command between
        # the speed update and the move.
        command = f"G01"
        if not (speed is None) and speed != self.current_speed:
            command += f" F{speed}"
            if update_current_speed:
                self.current_speed = speed

        self.send_gcode(f"{command} X{x} Y{y}")
        

    def _set_scale_to_mm(self) -> None:
        self.send_gcode("G21")


    def arc_clock_wise(self,x:float,y:float,I:float,J:float) -> None:
        self.send_gcode(f"G02 X{x} Y{y} I{I} J{J}")

    def arc_counter_clock_wise(self,x:float,y:float,I:float,J:float) -> None:
        self.send_gcode(f"G03 X{x} Y{y} I{I} J{J}")

def convert_svg_to_gcode_vpype(path_input_file: str, path_output_file: str,
                               profile: str = "idrawv2"):
    """
    usage example:
        convert_svg_to_gcode_vpype("./input.svg","./output.gcode")
    """
    # When the venv is not activated, its console scripts may not be on PATH.
    # Prefer PATH for normal installs, then look beside the Python interpreter
    # that is running this application.
    vpype = shutil.which("vpype")
    if vpype is None:
        interpreter_dir = os.path.dirname(sys.executable)
        candidate = os.path.join(interpreter_dir, "vpype")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            vpype = candidate
    if vpype is None:
        raise RuntimeError(
            "vpype is not installed in the active Python environment; "
            "run 'python -m pip install -r requirements.txt'"
        )

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "vpype-settings.toml")
    command = [
        vpype, "--config", config_path, "read", path_input_file,
    ]

    if profile == "idrawv2":
        # The iDraw X axis is reversed relative to SVG/vpype coordinates.
        # Reflect around the page's vertical center so text is not plotted
        # backwards.  Scaling first gives -X, then translating by the page
        # width maps it back into the positive coordinate range.
        with open(path_input_file, "r", encoding="utf-8") as svg_file:
            svg_header = svg_file.read(4096)
        width_match = re.search(r"\bwidth\s*=\s*[\"']\s*([0-9.+-]+)\s*(mm|cm|in|pt|pc|px)?", svg_header, re.I)
        if width_match is None:
            raise ValueError("SVG must specify a page width for iDraw X-axis correction")

        width = float(width_match.group(1))
        unit = (width_match.group(2) or "px").lower()
        width *= {
            "mm": 1.0,
            "cm": 10.0,
            "in": 25.4,
            "pt": 25.4 / 72.0,
            "pc": 25.4 / 6.0,
            "px": 25.4 / 96.0,
        }[unit]
        command.extend(["scale", "-o", "0", "0", "--", "-1", "1",
                        "translate", f"{width}mm", "0"])

    command.extend(["gwrite", "--profile", profile, path_output_file])
    subprocess.run(command, check=True)



def execute_raw_gcode_from_file(pen:AutoPen,path_gcode_file:str) -> None:
    commands = []
    
    #read and preprocess
    with open(path_gcode_file, 'r') as file:
        for line in file:
            command = line.strip().split(";")[0]

            if(not len(command) == 0):
                commands.append(command)

    #execute 
    for command in tqdm(commands,ascii=True,total=len(commands)):
        pen.send_gcode(command)


def plot_svg(pen:AutoPen,image_path:str,temp_gcode_file_path:str="./output.gcode") -> None:
    convert_svg_to_gcode_vpype(image_path,temp_gcode_file_path)
    execute_raw_gcode_from_file(pen,temp_gcode_file_path)


def multilayer_svg(pen:AutoPen,image_paths:list[str],temp_gcode_file_path:str="./output.gcode"):
        for path in image_paths:
            while(True):
                user_input = input("continue? Type 'y' to continue\n")
                if(user_input == "y"):
                    break 
            
            plot_svg(pen,path,temp_gcode_file_path)

if __name__ == "__main__":        
    pen = AutoPen()
    plot_svg(pen=pen,image_path="../assets/A0-70x100-C.svg",temp_gcode_file_path="./output.gcode")
