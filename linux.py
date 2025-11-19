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
DEBUG = True

# -----------------------
# Load config (optional)
# -----------------------
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
        e.ABS_Z: (0, 255, 0, 0),
        e.ABS_RZ: (0, 255, 0, 0),
        e.ABS_HAT0X: (-1, 1, 0, 0),
        e.ABS_HAT0Y: (-1, 1, 0, 0),
    },
    e.EV_FF: { e.FF_RUMBLE }
}

# -----------------------
# Mappings & helpers
# -----------------------
button_map = {
    'BTN_0': e.BTN_A, 'BTN_1': e.BTN_B, 'BTN_2': e.BTN_X, 'BTN_3': e.BTN_Y,
    'BTN_4': e.BTN_TL, 'BTN_5': e.BTN_TR, 'BTN_6': e.BTN_SELECT, 'BTN_7': e.BTN_START,
    'BTN_9': e.BTN_THUMBL, 'BTN_10': e.BTN_THUMBR,
    'HAT_0_UP': e.BTN_DPAD_UP, 'HAT_0_DOWN': e.BTN_DPAD_DOWN,
    'HAT_0_LEFT': e.BTN_DPAD_LEFT, 'HAT_0_RIGHT': e.BTN_DPAD_RIGHT
}

axis_map = {
    'AXIS_0': e.ABS_X, 'AXIS_1': e.ABS_Y,
    'AXIS_3': e.ABS_RX, 'AXIS_4': e.ABS_RY,
    'AXIS_2': e.ABS_Z,  'AXIS_5': e.ABS_RZ,
    'HAT_0': (e.ABS_HAT0X, e.ABS_HAT0Y)
}

def make_empty_state():
    return {
        'buttons': set(),
        'axes': {
            'LS_x': 0, 'LS_y': 0,
            'RS_x': 0, 'RS_y': 0,
            'LT': 0, 'RT': 0
        },
        'dpad': (0, 0)
    }

# -----------------------
# Global server state
# -----------------------
clients = {}                # client_id -> (conn, addr)
client_states = {}          # client_id -> state dict
clients_lock = threading.Lock()
next_client_id = 1


root = None
notebook = None
client_tabs = {}            # client_id -> (frame, widgets dict)
status_label_var = None

# -----------------------
# Event handling (writes to virtual device)
# -----------------------
current_dpad_buttons = set()

def handle_event(ui,client_id,code, value, target_state=None):
    #print(f"user:{client_id}  code:{code} value:{value} ") 
    """Apply event to virtual device and optionally to a per-client state dict (target_state)."""
    global current_dpad_buttons

    if target_state is None:
        pass

    # BUTTONS
    if isinstance(code, str) and code.startswith("BTN_"):
        ev = button_map.get(code)
        if ev is not None:
            try:
                ui.write(e.EV_KEY, ev, int(value))
                ui.syn()
            except Exception:
                if DEBUG: print("❌ evdev write error for button:", traceback.format_exc())
        # update per-client UI state
        if target_state is not None:
            if value:
                target_state['buttons'].add(code)
            else:
                target_state['buttons'].discard(code)

    # AXES (single numeric or already scaled)
    elif isinstance(code, str) and code.startswith("AXIS_"):
        ev = axis_map.get(code)
        if isinstance(ev, int):
            # value might be float in -1..1 or int already
            try:
                if isinstance(value, float) and abs(value) <= 1:
                    val = int(value * 32767)
                else:
                    val = int(value)
                ui.write(e.EV_ABS, ev, val)
                ui.syn()
            except Exception:
                if DEBUG: print("❌ evdev write error for axis:", traceback.format_exc())

        # update per-client UI state
        if target_state is not None:
            if code == "AXIS_0": target_state['axes']['LS_x'] = value
            if code == "AXIS_1": target_state['axes']['LS_y'] = value
            if code == "AXIS_2": target_state['axes']['RS_x'] = value
            if code == "AXIS_3": target_state['axes']['RS_y'] = value
            if code == "AXIS_4":
                try:
                    target_state['axes']['LT'] = (value + 1) / 2 if isinstance(value, (int, float)) else value
                except:
                    pass
            if code == "AXIS_5":
                try:
                    target_state['axes']['RT'] = (value + 1) / 2 if isinstance(value, (int, float)) else value
                except:
                    pass

    # HAT (x,y)
    elif code == "HAT_0":
        x, y = value
        # clear previous
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
        except Exception:
            if DEBUG: print("❌ evdev write error for hat:", traceback.format_exc())

        if target_state is not None:
            target_state['dpad'] = (x, y)

def apply_full_state(ui,client_id,data, target_state=None):
    for i, val in enumerate(data.get('axes', [])):
        handle_event(ui,client_id,f"AXIS_{i}", val, target_state=target_state)
    for i, val in enumerate(data.get('buttons', [])):
        handle_event(ui,client_id,f"BTN_{i}", val, target_state=target_state)
    handle_event(ui,client_id,"HAT_0", data.get('hat', (0,0)), target_state=target_state)

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

                # process event and update per-client state
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
                    elif etype == 'debug':
                        print(f"[DEBUG #{client_id}] {event.get('data')}")
                    else:
                        if DEBUG:
                            print(f"[CLIENT {client_id}] Unknown event type: {etype}")
                except Exception:
                    print(f"❌ Error processing event from client #{client_id}:\n{traceback.format_exc()}")

                # prepare and send response
                with clients_lock:
                    client_count = len(clients)
                response = {
                    "CLIENT_ID": client_id,
                    "CLIENT_COUNT": client_count
                }
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
    sock.bind(("192.168.1.10", SERVER_PORT))
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
            # create UI tab
            create_client_tab(client_id, addr)
            update_status_label()
            t = threading.Thread(target=handle_client, args=(conn, addr, client_id), daemon=True)
            t.start()
        except Exception as ex:
            print("❌ Socket accept error:", ex)

def config_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", CONFIG_PORT))
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

# -----------------------
# Tkinter UI: tabs per client
# -----------------------
def create_client_tab(client_id, addr):
    """Create a new tab for client_id in the notebook (called from server thread)."""
    if not SHOW_UI:
        return
    def _create():
        global notebook, client_tabs
        tab = ttk.Frame(notebook)
        notebook.add(tab, text=f"Client #{client_id}")
        # top label with address
        lbl = tk.Label(tab, text=f"ID: {client_id} — {addr[0]}:{addr[1]}", bg="black", fg="white")
        lbl.pack(anchor="w", pady=(4,0))
        # small status label to show button list
        btn_frame = tk.Frame(tab, bg="black")
        btn_frame.pack(side="left", padx=8, pady=8, anchor="n")
        # Canvas to draw buttons/axes/dpad for this client
        canvas = tk.Canvas(tab, width=420, height=300, bg="black")
        canvas.pack(side="left", padx=6, pady=6)

        client_tabs[client_id] = {
            'frame': tab,
            'label': lbl,
            'canvas': canvas,
        }
    # UI actions must run in main thread
    try:
        root.after(0, _create)
    except Exception:
        # if root isn't available, ignore (headless)
        pass

def remove_client_tab(client_id):
    """Remove tab for client_id from notebook (called by network threads)."""
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
    """Update the small status label and window title with count"""
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
    """Draw the client's inputs onto its canvas (called periodically from UI thread)."""
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

    # Header
    canvas.create_text(210, 18, text=f"Client #{client_id}", fill="white")

    # Buttons (positions similar to your original layout)
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

    # Triggers LT / RT
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
    """Called periodically in the UI thread to redraw all client canvases."""
    if not SHOW_UI:
        return
    for cid in list(client_tabs.keys()):
        draw_client_canvas(cid)
    root.after(50, ui_refresh_loop)

def run_ui():
    """Starts Tkinter UI: Notebook tabs for each client and status label."""
    global root, notebook, status_label_var
    root = tk.Tk()
    root.configure(bg="black")
    root.title("Controller UI — 0 clients")

    # Notebook (tabs)
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=6, pady=6)

    # status label
    status_label_var = tk.StringVar(value="Connected clients: 0")
    status_label = tk.Label(root, textvariable=status_label_var, bg="black", fg="white")
    status_label.pack(anchor="w", padx=6, pady=(0,6))

    # start periodic UI refresh
    root.after(50, ui_refresh_loop)
    root.mainloop()

# -----------------------
# Main entry
# -----------------------
if __name__ == "__main__":
    threading.Thread(target=config_server, daemon=True).start()
    threading.Thread(target=controller_server, daemon=True).start()

    # Run UI in main thread if desired
    if SHOW_UI:
        run_ui()
    else:
        threading.Event().wait()