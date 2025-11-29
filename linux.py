import socket
import json
import threading
import tkinter as tk
from tkinter import ttk
from evdev import UInput, ecodes as e, ff
import os
import traceback

SERVER_PORT = 5000
SHOW_UI = True

# ---------------------------------------------------------
# Virtual Controller Setup
# ---------------------------------------------------------
ui = UInput({
    e.EV_KEY: [
        e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
        e.BTN_TL, e.BTN_TR,
        e.BTN_SELECT, e.BTN_START,
        e.BTN_THUMBL, e.BTN_THUMBR,
    ],
    e.EV_ABS: {
        e.ABS_X: (-32768, 32767, 0, 0),
        e.ABS_Y: (-32768, 32767, 0, 0),
        e.ABS_RX: (-32768, 32767, 0, 0),
        e.ABS_RY: (-32768, 32767, 0, 0),
        e.ABS_Z: (0, 255, 0, 0),     # LT
        e.ABS_RZ: (0, 255, 0, 0),    # RT
    },
    e.EV_FF: [e.FF_RUMBLE],
})

# Make global rumble effect
rumble_effect = ff.Effect(
    e.FF_RUMBLE,
    -1,
    0,
    ff.Trigger(0, 0),
    ff.Replay(250, 0),  # 250ms rumble
    ff.EffectType(ff.Rumble(0, 0))
)

rumble_id = ui.upload_effect(rumble_effect)

def play_rumble(strength: float):
    """ strength = 0.0 – 1.0 """
    mag = int(0xFFFF * strength)

    rumble_effect.u.rumble.weak_magnitude = mag
    rumble_effect.u.rumble.strong_magnitude = mag

    ui.upload_effect(rumble_effect)
    ui.write(e.EV_FF, rumble_id, 1)
    ui.syn()

# ---------------------------------------------------------
# Per-client storage
# ---------------------------------------------------------
clients = {}  # key = addr , value = {widgets + rumble value}

# ---------------------------------------------------------
# UI
# ---------------------------------------------------------
root = tk.Tk() if SHOW_UI else None
if SHOW_UI:
    root.title("Receiver Controller Status")
    container = ttk.Frame(root)
    container.pack(fill="both", expand=True)

def create_client_ui(addr):
    frame = ttk.LabelFrame(container, text=f"Client {addr}")
    frame.pack(fill="x", padx=5, pady=5)

    axes = {
        "LX": tk.DoubleVar(),
        "LY": tk.DoubleVar(),
        "RX": tk.DoubleVar(),
        "RY": tk.DoubleVar(),
        "LT": tk.DoubleVar(),
        "RT": tk.DoubleVar(),
        "Rumble": tk.DoubleVar(value=0.0)
    }

    row = 0
    for name, var in axes.items():
        ttk.Label(frame, text=name).grid(row=row, column=0)
        s = ttk.Scale(frame, from_=-1, to=1, variable=var, orient="horizontal", length=200)
        if name in ["LT", "RT", "Rumble"]:  
            s.configure(from_=0, to=1)
        s.grid(row=row, column=1)
        row += 1

    # Button to test rumble per-client
    def test_rumble():
        strength = axes["Rumble"].get()
        play_rumble(strength)

    ttk.Button(frame, text="Test Rumble", command=test_rumble).grid(row=row, column=0, columnspan=2, pady=4)

    return {"frame": frame, "axes": axes}

# ---------------------------------------------------------
# Processing incoming control packets
# ---------------------------------------------------------
def handle_event(event, client):
    etype = event["type"]

    # --------------------------
    # AXES / JOYSTICKS
    # --------------------------
    if etype == "axis":
        axis = event["axis"]
        value = event["value"]  # -1 to 1 on sender

        # UI update
        if axis == "LX": client["axes"]["LX"].set(value)
        elif axis == "LY": client["axes"]["LY"].set(value)
        elif axis == "RX": client["axes"]["RX"].set(value)
        elif axis == "RY": client["axes"]["RY"].set(value)

        # Mapping to virtual controller
        if axis == "LX": ui.write(e.EV_ABS, e.ABS_X, int(value * 32767))
        if axis == "LY": ui.write(e.EV_ABS, e.ABS_Y, int(value * 32767))
        if axis == "RX": ui.write(e.EV_ABS, e.ABS_RX, int(value * 32767))
        if axis == "RY": ui.write(e.EV_ABS, e.ABS_RY, int(value * 32767))

        ui.syn()

    # --------------------------
    # TRIGGERS
    # --------------------------
    elif etype == "trigger":
        which = event["which"]  # "LT" or "RT"
        val = event["value"]    # -1..1 from sender A (we map to 0–255)

        scaled = int(((val + 1) / 2) * 255)

        if which == "LT":
            client["axes"]["LT"].set((val + 1) / 2)
            ui.write(e.EV_ABS, e.ABS_Z, scaled)

        elif which == "RT":
            client["axes"]["RT"].set((val + 1) / 2)
            ui.write(e.EV_ABS, e.ABS_RZ, scaled)

        ui.syn()

    # --------------------------
    # BUTTONS
    # --------------------------
    elif etype == "button":
        btn = event["btn"]
        state = 1 if event["pressed"] else 0

        BUTTON_MAP = {
            "A": e.BTN_A, "B": e.BTN_B, "X": e.BTN_X, "Y": e.BTN_Y,
            "LB": e.BTN_TL, "RB": e.BTN_TR,
            "START": e.BTN_START, "SELECT": e.BTN_SELECT,
            "L3": e.BTN_THUMBL, "R3": e.BTN_THUMBR
        }

        if btn in BUTTON_MAP:
            ui.write(e.EV_KEY, BUTTON_MAP[btn], state)
            ui.syn()

    # --------------------------
    # RUMBLE
    # --------------------------
    elif etype == "rumble":
        strength = event["strength"]
        client["axes"]["Rumble"].set(strength)
        play_rumble(strength)


# ---------------------------------------------------------
# Client thread
# ---------------------------------------------------------
def client_thread(conn, addr):
    addr_str = f"{addr[0]}:{addr[1]}"
    print("Client connected:", addr_str)

    clients[addr_str] = create_client_ui(addr_str) if SHOW_UI else {}

    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break

            event = json.loads(data.decode())
            handle_event(event, clients[addr_str])

    except:
        traceback.print_exc()

    finally:
        print("Client disconnected:", addr_str)
        conn.close()


# ---------------------------------------------------------
# Start server
# ---------------------------------------------------------
def start_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", SERVER_PORT))
    s.listen(5)
    print("Receiver running on port", SERVER_PORT)

    while True:
        conn, addr = s.accept()
        threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()


threading.Thread(target=start_server, daemon=True).start()

if SHOW_UI:
    root.mainloop()
else:
    threading.Event().wait()
