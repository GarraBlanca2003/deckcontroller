import socket
import json
import threading
import tkinter as tk
from tkinter import ttk
from evdev import UInput, ecodes as e
import os
import traceback

# -----------------------
# Config / constants
# -----------------------
SHOW_UI = True
SERVER_PORT = 5000
CONFIG_PORT = 5001
CONFIG_PATH = "config.json"
USE_RUMBLE = False
SEND_FULL_STATE = False
DEBUG = False
PC_IP = "192.168.1.10"
if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
            USE_UDP = cfg.get("USE_UDP", False)
            USE_RUMBLE = cfg.get("USE_RUMBLE", False)
            SEND_FULL_STATE = cfg.get("SEND_FULL_STATE", SEND_FULL_STATE)
            DEBUG = cfg.get("DEBUG", DEBUG)
            print(f"🛠️ Loaded config: Rumble={USE_RUMBLE}, FullState={SEND_FULL_STATE}, Debug={DEBUG}")
    except Exception as ex:
        print("❌ Error reading config:", ex)

# -----------------------
# evdev virtual device
# -----------------------
capabilities = {
    e.EV_KEY: [
        e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
        e.BTN_TL, e.BTN_TR, e.BTN_SELECT, e.BTN_START,
        e.BTN_THUMBL, e.BTN_THUMBR,
        e.BTN_DPAD_UP, e.BTN_DPAD_DOWN, e.BTN_DPAD_LEFT, e.BTN_DPAD_RIGHT
    ],
    e.EV_ABS: {
        e.ABS_X: (-32768, 32767, 0, 0),
        e.ABS_Y: (-32768, 32767, 0, 0),
        e.ABS_RX: (-32768, 32767, 0, 0),
        e.ABS_RY: (-32768, 32767, 0, 0),
        # Changed triggers to 16-bit signed range to avoid mixed-scaling artifacts
        e.ABS_Z: (-32768, 32767, 0, 0),     # LT
        e.ABS_RZ: (-32768, 32767, 0, 0),    # RT
        e.ABS_HAT0X: (-1, 1, 0, 0),
        e.ABS_HAT0Y: (-1, 1, 0, 0),
        # Gyro/motion axes (for rotational data)
        e.ABS_WHEEL: (-32768, 32767, 0, 0),   # Rotation Z (yaw)
        e.ABS_TILT_X: (-32768, 32767, 0, 0),  # Rotation X (roll)
        e.ABS_TILT_Y: (-32768, 32767, 0, 0),  # Rotation Y (pitch)
    },
    e.EV_FF: { e.FF_RUMBLE }
}

# Mappings & helpers
button_map = {
    'BTN_0': e.BTN_A, 'BTN_1': e.BTN_B, 'BTN_2': e.BTN_X, 'BTN_3': e.BTN_Y,
    'BTN_4': e.BTN_TL, 'BTN_5': e.BTN_TR, 'BTN_6': e.BTN_SELECT, 'BTN_7': e.BTN_START,
    'BTN_9': e.BTN_THUMBL, 'BTN_10': e.BTN_THUMBR,
    'HAT_0_UP': e.BTN_DPAD_UP, 'HAT_0_DOWN': e.BTN_DPAD_DOWN,
    'HAT_0_LEFT': e.BTN_DPAD_LEFT, 'HAT_0_RIGHT': e.BTN_DPAD_RIGHT
}

axis_map = {
    'AXIS_0': e.ABS_X,   # Left stick X
    'AXIS_1': e.ABS_Y,   # Left stick Y
    'AXIS_3': e.ABS_RX,  # Right stick X
    'AXIS_4': e.ABS_RY,  # Right stick Y
    'AXIS_2': e.ABS_Z,   # Left trigger (LT)
    'AXIS_5': e.ABS_RZ,  # Right trigger (RT)
    'HAT_0': (e.ABS_HAT0X, e.ABS_HAT0Y),
    'GYRO_X': e.ABS_TILT_X,  # Gyro roll
    'GYRO_Y': e.ABS_TILT_Y,  # Gyro pitch
    'GYRO_Z': e.ABS_WHEEL,   # Gyro yaw
}

def make_empty_state():
    return {
        'buttons': set(),
        'axes': {
            'LS_x': 0.0, 'LS_y': 0.0,
            'RS_x': 0.0, 'RS_y': 0.0,
            'LT': 0.0, 'RT': 0.0,
            'GYRO_X': 0.0, 'GYRO_Y': 0.0, 'GYRO_Z': 0.0
        },
        'dpad': (0, 0)
    }

# -----------------------
# Global server state
# -----------------------
clients = {}
client_states = {}
clients_lock = threading.Lock()
next_client_id = 1

root = None
notebook = None
client_tabs = {}
status_label_var = None

current_dpad_buttons = set()

def handle_event(ui,client_id,code, value, target_state=None):
    global current_dpad_buttons

    if target_state is None:
        pass

    # BUTTONS
    if isinstance(code, str) and code.startswith("BTN_"):
        ev = button_map.get(code)
        if ev is not None:
            try:
                ui.write(e.EV_KEY, ev, int(bool(value)))
                ui.syn()
            except Exception as ex:
                if DEBUG: print(f"❌ evdev write error for button {code}:", ex)
        if target_state is not None:
            if value:
                target_state['buttons'].add(code)
            else:
                target_state['buttons'].discard(code)

    # AXES
    elif isinstance(code, str) and code.startswith("AXIS_"):
        ev = axis_map.get(code)
        if isinstance(ev, int):
            # If this is a trigger (ABS_Z or ABS_RZ) we map from -1..1 -> -32767..32767
            if ev in (e.ABS_Z, e.ABS_RZ):
                try:
                    if isinstance(value, (int, float)):
                        v = float(value)
                        # clamp
                        if v < -1.0: v = -1.0
                        if v > 1.0: v = 1.0
                        # map -1..1 -> -32767..32767 (signed 16-bit)
                        scaled = int(round(v * 32767.0))
                    else:
                        scaled = int(value)
                    ui.write(e.EV_ABS, ev, scaled)
                    ui.syn()
                except Exception as ex:
                    if DEBUG: print(f"❌ evdev write error for trigger axis {code}:", ex)
            else:
                # Non-trigger axis (sticks): -1..1 -> -32767..32767
                try:
                    if isinstance(value, (int, float)) and abs(float(value)) <= 1:
                        val = int(round(float(value) * 32767.0))
                    else:
                        val = int(value)
                    ui.write(e.EV_ABS, ev, val)
                    ui.syn()
                except Exception as ex:
                    if DEBUG: print(f"❌ evdev write error for axis {code}:", ex)

        # update per-client UI state mapping
        if target_state is not None:
            if code == "AXIS_0":
                target_state['axes']['LS_x'] = float(value) if isinstance(value, (int, float)) else 0.0
            elif code == "AXIS_1":
                target_state['axes']['LS_y'] = float(value) if isinstance(value, (int, float)) else 0.0
            elif code == "AXIS_3":
                target_state['axes']['RS_x'] = float(value) if isinstance(value, (int, float)) else 0.0
            elif code == "AXIS_4":
                target_state['axes']['RS_y'] = float(value) if isinstance(value, (int, float)) else 0.0
            elif code == "AXIS_2":
                try:
                    v = float(value)
                    target_state['axes']['LT'] = (v + 1.0) / 2.0
                except:
                    pass
            elif code == "AXIS_5":
                try:
                    v = float(value)
                    target_state['axes']['RT'] = (v + 1.0) / 2.0
                except:
                    pass

    # GYRO/MOTION AXES
    elif isinstance(code, str) and code.startswith("GYRO_"):
        ev = axis_map.get(code)
        if isinstance(ev, int):
            try:
                if isinstance(value, (int, float)):
                    v = float(value)
                    # Clamp and scale gyro data: -1..1 -> -32767..32767
                    if v < -1.0: v = -1.0
                    if v > 1.0: v = 1.0
                    scaled = int(round(v * 32767.0))
                else:
                    scaled = int(value)
                ui.write(e.EV_ABS, ev, scaled)
                ui.syn()
            except Exception as ex:
                if DEBUG: print("❌ evdev write error for gyro:", ex)
        
        if target_state is not None:
            if code == "GYRO_X":
                target_state['axes']['GYRO_X'] = float(value) if isinstance(value, (int, float)) else 0.0
            elif code == "GYRO_Y":
                target_state['axes']['GYRO_Y'] = float(value) if isinstance(value, (int, float)) else 0.0
            elif code == "GYRO_Z":
                target_state['axes']['GYRO_Z'] = float(value) if isinstance(value, (int, float)) else 0.0

    # HAT
    elif code == "HAT_0":
        x, y = value
        for btn in list(current_dpad_buttons):
            try:
                ui.write(e.EV_KEY, btn, 0)
            except:
                pass
        current_dpad_buttons.clear()

        if x == -1:
            ui.write(e.EV_KEY, e.BTN_DPAD_LEFT, 1); current_dpad_buttons.add(e.BTN_DPAD_LEFT)
        elif x == 1:
            ui.write(e.EV_KEY, e.BTN_DPAD_RIGHT, 1); current_dpad_buttons.add(e.BTN_DPAD_RIGHT)

        if y == 1:
            ui.write(e.EV_KEY, e.BTN_DPAD_UP, 1); current_dpad_buttons.add(e.BTN_DPAD_UP)
        elif y == -1:
            ui.write(e.EV_KEY, e.BTN_DPAD_DOWN, 1); current_dpad_buttons.add(e.BTN_DPAD_DOWN)

        try:
            ui.write(e.EV_ABS, e.ABS_HAT0X, x)
            ui.write(e.EV_ABS, e.ABS_HAT0Y, y)
            ui.syn()
        except Exception as ex:
            if DEBUG: print(f"❌ evdev write error for hat:", ex)

        if target_state is not None:
            target_state['dpad'] = (x, y)

def apply_full_state(ui,client_id,data, target_state=None):
    try:
        for i, val in enumerate(data.get('axes', [])):
            handle_event(ui, client_id, f"AXIS_{i}", val, target_state=target_state)
        for i, val in enumerate(data.get('buttons', [])):
            handle_event(ui, client_id, f"BTN_{i}", val, target_state=target_state)
        handle_event(ui, client_id, "HAT_0", data.get('hat', (0,0)), target_state=target_state)
        
        # Handle gyro if present
        gyro_data = data.get('gyro')
        if gyro_data:
            handle_event(ui, client_id, "GYRO_X", gyro_data.get('x', 0), target_state=target_state)
            handle_event(ui, client_id, "GYRO_Y", gyro_data.get('y', 0), target_state=target_state)
            handle_event(ui, client_id, "GYRO_Z", gyro_data.get('z', 0), target_state=target_state)
    except Exception as ex:
        if DEBUG:
            print(f"❌ Error applying full state: {ex}")
            traceback.print_exc()

def handle_client(conn, addr, client_id):
    global clients, client_states
    ui = UInput(capabilities, name=f"Virtual Gamepad -{client_id}", version=0x3, bustype=e.BUS_USB)
    print(f"🔌 Client #{client_id} handler started for {addr}")
    buffer = ""
    try:
        conn.settimeout(None)
        while True:
            data = conn.recv(4096)
            if not data:
                print(f"⚠️ Client #{client_id} disconnected (no data).")
                break
            buffer += data.decode(errors='ignore')
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                print (line)
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception as ex:
                    print(f"❌ Client #{client_id} JSON decode error: {ex} -- raw: {line!r}")
                    continue

                st = None
                with clients_lock:
                    st = client_states.get(client_id)
                try:
                    etype = event.get('type')
                    if etype == 'gamepad':
                        d = event.get('data', {})
                        handle_event(ui,client_id,d.get('code'), d.get('state'), target_state=st)
                    elif etype == 'full_state':
                        apply_full_state(ui,client_id,event.get('data', {}), target_state=st)
                    elif etype == 'gyro':
                        d = event.get('data', {})
                        handle_event(ui, client_id, "GYRO_X", d.get('x', 0), target_state=st)
                        handle_event(ui, client_id, "GYRO_Y", d.get('y', 0), target_state=st)
                        handle_event(ui, client_id, "GYRO_Z", d.get('z', 0), target_state=st)
                    elif etype == 'debug':
                        print(f"[DEBUG #{client_id}] {event.get('data')}")
                    else:
                        if DEBUG:
                            print(f"[CLIENT {client_id}] Unknown event type: {etype}")
                except Exception as ex:
                    print(f"❌ Error processing event from client #{client_id}: {ex}")
                    if DEBUG:
                        traceback.print_exc()

                with clients_lock:
                    client_count = len(clients)
                response = {"CLIENT_ID": client_id, "CLIENT_COUNT": client_count}
                try:
                    conn.sendall((json.dumps(response) + "\n").encode())
                except Exception as ex:
                    print(f"❌ Error sending to client #{client_id}: {ex}")
                    raise

    except Exception as ex:
        print(f"❌ Socket error in client #{client_id} handler: {ex}")
    finally:
        try:
            ui.close()
            conn.close()
        except:
            pass
        with clients_lock:
            if client_id in clients: del clients[client_id]
            if client_id in client_states: del client_states[client_id]

        remove_client_tab(client_id)
        print(f"📴 Client #{client_id} disconnected. Connected clients: {len(clients)}")
        update_status_label()

def controller_server():
    global next_client_id, clients
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((PC_IP, SERVER_PORT))
    sock.listen(10)
    print(f"🎮 Controller server listening on port {SERVER_PORT}")
    while True:
        try:
            conn, addr = sock.accept()
            with clients_lock:
                client_id = next_client_id
                next_client_id += 1
                clients[client_id] = (conn, addr)
                client_states[client_id] = make_empty_state()
            print(f"✅ New connection from {addr} assigned Client ID #{client_id}. Total clients: {len(clients)}")
            create_client_tab(client_id, addr)
            update_status_label()
            t = threading.Thread(target=handle_client, args=(conn, addr, client_id), daemon=True)
            t.start()
        except Exception as ex:
            print("❌ Socket accept error:", ex)

def config_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((PC_IP, CONFIG_PORT))
        s.listen(5)
        print("📡 Config server running on port", CONFIG_PORT)
        while True:
            conn, addr = s.accept()
            with conn:
                config_data = json.dumps({
                    "USE_UDP": False,
                    "SEND_FULL_STATE": SEND_FULL_STATE,
                    "RUMBLE": USE_RUMBLE,
                    "DEBUG": DEBUG
                })
                try:
                    conn.sendall((config_data + "\n").encode())
                except Exception as e:
                    print("❌ Error sending config:", e)

# UI helpers (unchanged)...
def create_client_tab(client_id, addr):
    if not SHOW_UI:
        return
    def _create():
        global notebook, client_tabs
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=f"Client #{client_id}")
        lbl = tk.Label(tab, text=f"ID: {client_id} — {addr[0]}:{addr[1]}", bg="black", fg="white")
        lbl.pack(anchor="w", pady=(4,0))
        btn_frame = tk.Frame(tab, bg="black")
        btn_frame.pack(side="left", padx=8, pady=8, anchor="n")
        canvas = tk.Canvas(tab, width=420, height=300, bg="black")
        canvas.pack(side="left", padx=6, pady=6)
        client_tabs[client_id] = {'frame': tab, 'label': lbl, 'canvas': canvas}
    try:
        root.after(0, _create)
    except Exception:
        pass

def remove_client_tab(client_id):
    if not SHOW_UI:
        return
    def _remove():
        global notebook, client_tabs
        entry = client_tabs.pop(client_id, None)
        if entry:
            try:
                notebook.forget(entry['frame'])
            except Exception:
                pass
    try:
        root.after(0, _remove)
    except Exception:
        pass

def update_status_label():
    if not SHOW_UI:
        return
    def _update():
        count = 0
        with clients_lock:
            count = len(clients)
        if status_label_var is not None:
            status_label_var.set(f"Connected clients: {count}")
        try:
            root.title(f"Controller UI — {count} clients")
        except Exception:
            pass
    try:
        root.after(0, _update)
    except Exception:
        pass

def draw_client_canvas(client_id):
    entry = client_tabs.get(client_id)
    if not entry:
        return
    canvas = entry['canvas']
    canvas.delete("all")
    st = None
    with clients_lock:
        st = client_states.get(client_id)
    if st is None:
        canvas.create_text(200, 140, text="No state yet", fill="white")
        return
    canvas.create_text(210, 18, text=f"Client #{client_id}", fill="white")

    def dpad_active(name):
        x, y = st['dpad']
        return (
            (name == "HAT_0_UP" and y == 1) or
            (name == "HAT_0_DOWN" and y == -1) or
            (name == "HAT_0_LEFT" and x == -1) or
            (name == "HAT_0_RIGHT" and x == 1)
        )
    def draw_btn(name, x, y):
        color = "lime" if (name in st['buttons'] or dpad_active(name)) else "gray"
        canvas.create_oval(x-10, y-10, x+10, y+10, fill=color)

    draw_btn("BTN_0", 300, 150)
    draw_btn("BTN_1", 330, 120)
    draw_btn("BTN_2", 270, 120)
    draw_btn("BTN_3", 300, 90)
    draw_btn("HAT_0_UP", 70, 100)
    draw_btn("HAT_0_DOWN", 70, 140)
    draw_btn("HAT_0_LEFT", 40, 120)
    draw_btn("HAT_0_RIGHT", 100, 120)
    draw_btn("BTN_4", 100, 40)
    draw_btn("BTN_5", 300, 40)
    draw_btn("BTN_6", 180, 100)
    draw_btn("BTN_7", 220, 100)
    draw_btn("BTN_8", 100, 200)
    draw_btn("BTN_9", 300, 200)

    # Triggers LT / RT (st['axes']['LT'] and RT are 0..1 floats)
    canvas.create_text(70, 250, text="LT", fill="white")
    canvas.create_rectangle(100, 240, 150, 260, outline="white")
    try:
        canvas.create_rectangle(100, 240, 100 + int(50 * float(st['axes']['LT'])), 260, fill="red")
    except Exception:
        canvas.create_rectangle(100, 240, 100, 260, fill="red")

    canvas.create_text(250, 250, text="RT", fill="white")
    canvas.create_rectangle(280, 240, 330, 260, outline="white")
    try:
        canvas.create_rectangle(280, 240, 280 + int(50 * float(st['axes']['RT'])), 260, fill="red")
    except Exception:
        canvas.create_rectangle(280, 240, 280, 260, fill="red")

    # Left stick
    try:
        lx = 100 + int(float(st['axes']['LS_x']) * 20)
        ly = 200 + int(float(st['axes']['LS_y']) * 20)
        canvas.create_oval(lx-5, ly-5, lx+5, ly+5, fill="blue")
    except Exception:
        canvas.create_oval(95, 195, 105, 205, fill="blue")

    # Right stick
    try:
        rx = 300 + int(float(st['axes']['RS_x']) * 20)
        ry = 200 + int(float(st['axes']['RS_y']) * 20)
        canvas.create_oval(rx-5, ry-5, rx+5, ry+5, fill="blue")
    except Exception:
        canvas.create_oval(295, 195, 305, 205, fill="blue")

def ui_refresh_loop():
    if not SHOW_UI:
        return
    for cid in list(client_tabs.keys()):
        draw_client_canvas(cid)
    root.after(50, ui_refresh_loop)

def run_ui():
    global root, notebook, status_label_var
    root = tk.Tk()
    root.configure(bg="black")
    root.title("Controller UI — 0 clients")
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=6, pady=6)
    status_label_var = tk.StringVar(value="Connected clients: 0")
    status_label = tk.Label(root, textvariable=status_label_var, bg="black", fg="white")
    status_label.pack(anchor="w", padx=6, pady=(0,6))

    # start periodic UI refresh
    root.after(50, ui_refresh_loop)
    root.mainloop()

if __name__ == "__main__":
    threading.Thread(target=config_server, daemon=True).start()
    threading.Thread(target=controller_server, daemon=True).start()
    if SHOW_UI:
        run_ui()
    else:
        threading.Event().wait()
