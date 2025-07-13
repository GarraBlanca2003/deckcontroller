import socket
import json
import threading
import tkinter as tk
from evdev import UInput, ecodes as e

HOST = '0.0.0.0'
PORT = 65432
SHOW_UI = True

# === UInput Setup ===
capabilities = {
    e.EV_KEY: [e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
               e.BTN_TL, e.BTN_TR, e.BTN_SELECT, e.BTN_START,
               e.BTN_DPAD_UP, e.BTN_DPAD_DOWN, e.BTN_DPAD_LEFT, e.BTN_DPAD_RIGHT]
}
ui = UInput(capabilities, name="Virtual Controller", bustype=e.BUS_USB)

# === UI Setup ===
class ControllerUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Controller State")
        self.geometry("300x300")
        self.labels = {}

        for idx, name in enumerate(capabilities[e.EV_KEY]):
            label = tk.Label(self, text=f"{e.KEY[name] if name in e.KEY else name}: OFF", font=("Arial", 12))
            label.pack()
            self.labels[name] = label

    def update_button(self, code, state):
        if code in self.labels:
            text = f"{e.KEY[code] if code in e.KEY else code}: {'ON' if state else 'OFF'}"
            self.labels[code].config(text=text)

controller_ui = ControllerUI() if SHOW_UI else None

def handle_client(conn, addr):
    print(f"[+] Connected by {addr}")
    try:
        with conn:
            while True:
                data = conn.recv(1024)
                if not data:
                    break

                try:
                    events = json.loads(data.decode())
                    for code_str, state in events.items():
                        code = getattr(e, code_str, None)
                        if code:
                            ui.write(e.EV_KEY, code, int(state))
                            if controller_ui:
                                controller_ui.update_button(code, state)
                    ui.syn()
                except json.JSONDecodeError:
                    print("[!] Failed to parse input.")
    finally:
        print(f"[-] Disconnected: {addr}")

def tcp_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        print(f"[+] TCP Server listening on {HOST}:{PORT}")
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

threading.Thread(target=tcp_server, daemon=True).start()
if SHOW_UI:
    controller_ui.mainloop()
else:
    threading.Event().wait()
