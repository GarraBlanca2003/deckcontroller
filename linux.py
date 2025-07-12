import socket
import json
import threading
import tkinter as tk
from evdev import UInput, ecodes as e

SHOW_UI = False
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
    }
}

ui = UInput(capabilities, name="Virtual Gamepad", version=0x3)

button_map = {
    'BTN_0': e.BTN_A, 'BTN_1': e.BTN_B, 'BTN_2': e.BTN_X, 'BTN_3': e.BTN_Y,
    'BTN_4': e.BTN_TL,
    'BTN_5': e.BTN_TR,
    'BTN_6': e.BTN_SELECT,
    'BTN_7': e.BTN_START,
    'BTN_9': e.BTN_THUMBL,
    'BTN_10': e.BTN_THUMBR,
    'HAT_0_UP': e.BTN_DPAD_UP, 'HAT_0_DOWN': e.BTN_DPAD_DOWN,
    'HAT_0_LEFT': e.BTN_DPAD_LEFT, 'HAT_0_RIGHT': e.BTN_DPAD_RIGHT
}

axis_map = {
    'AXIS_0': e.ABS_X, 'AXIS_1': e.ABS_Y,
    'AXIS_3': e.ABS_RX, 'AXIS_4': e.ABS_RY,
    'AXIS_2': e.ABS_Z,  'AXIS_5': e.ABS_RZ,
    'HAT_0': (e.ABS_HAT0X, e.ABS_HAT0Y)
}
state = {
    'buttons': set(),
    'axes': {
        'LS_x': 0, 'LS_y': 0,
        'RS_x': 0, 'RS_y': 0,
        'LT': 0, 'RT': 0
    },
    'dpad': (0, 0)
}

current_dpad_buttons = set()

# I. handler
def handle_event(code, value):
    #if not code.startswith("AXIS_"):
    #    print(f'code : {code} : {value}')
    
    if code.startswith("BTN_"):
        ev = button_map.get(code)
        if ev:
            ui.write(e.EV_KEY, ev, int(value))
            ui.syn()
        if SHOW_UI:
            if value:
                state['buttons'].add(code)
            else:
                state['buttons'].discard(code)

    elif code.startswith("AXIS_"):
        ev = axis_map.get(code)
        if isinstance(ev, int):
            if ev in (e.ABS_X, e.ABS_Y, e.ABS_RX, e.ABS_RY):
                val = int(value * 32767)
            else:
                val = int(value * 32767)
            ui.write(e.EV_ABS, ev, val)
            ui.syn()

        if SHOW_UI:
            if code == "AXIS_0": state['axes']['LS_x'] = value
            if code == "AXIS_1": state['axes']['LS_y'] = value
            if code == "AXIS_3": state['axes']['RS_x'] = value
            if code == "AXIS_4": state['axes']['RS_y'] = value
            if code == "AXIS_2": state['axes']['LT'] = (value + 1) / 2
            if code == "AXIS_5": state['axes']['RT'] = (value + 1) / 2

    elif code == "HAT_0":
        global current_dpad_buttons
        x, y = value
        
        for btn in current_dpad_buttons:
            ui.write(e.EV_KEY, btn, 0)
        current_dpad_buttons.clear()
        
        if x == -1:  # Left
            ui.write(e.EV_KEY, e.BTN_DPAD_LEFT, 1)
            current_dpad_buttons.add(e.BTN_DPAD_LEFT)
        elif x == 1:  # Right
            ui.write(e.EV_KEY, e.BTN_DPAD_RIGHT, 1)
            current_dpad_buttons.add(e.BTN_DPAD_RIGHT)
            
        if y == 1:  # Up
            ui.write(e.EV_KEY, e.BTN_DPAD_UP, 1)
            current_dpad_buttons.add(e.BTN_DPAD_UP)
        elif y == -1:  #Down
            ui.write(e.EV_KEY, e.BTN_DPAD_DOWN, 1)
            current_dpad_buttons.add(e.BTN_DPAD_DOWN)

        ui.write(e.EV_ABS, e.ABS_HAT0X, x)
        ui.write(e.EV_ABS, e.ABS_HAT0Y, y)
        ui.syn()
        
        if SHOW_UI:
            state['dpad'] = (x, y)

def socket_thread():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 5000))
    sock.listen(1)
    print("🎮 Waiting for deck...")

    while True:
        try:
            conn, addr = sock.accept()
            print(f"✅ Connected to {addr}")

            buffer = ""
            while True:
                data = conn.recv(1024)
                if not data:
                    print("⚠️ Connection closed by client.")
                    break

                buffer += data.decode()
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    try:
                        event = json.loads(line)
                        if event['type'] == 'gamepad':
                            handle_event(event['data']['code'], event['data']['state'])
                    except Exception as ex:
                        print("❌ JSON decode error:", ex)

        except Exception as ex:
            print("❌ Socket error:", ex)

        print("🔄 Waiting for new connection...")


def run_ui():
    root = tk.Tk()
    root.title("Controller UI")
    canvas = tk.Canvas(root, width=400, height=300, bg="black")
    canvas.pack()

    def dpad_active(name):
        x, y = state['dpad']
        return (
            (name == "HAT_0_UP" and y == -1) or
            (name == "HAT_0_DOWN" and y == 1) or
            (name == "HAT_0_LEFT" and x == -1) or
            (name == "HAT_0_RIGHT" and x == 1)
        )

    def draw_btn(name, x, y):
        color = "lime" if name in state['buttons'] or dpad_active(name) else "gray"
        canvas.create_oval(x-10, y-10, x+10, y+10, fill=color)

    def redraw():
        canvas.delete("all")
        canvas.create_text(200, 20, text="Gamepad Monitor", fill="white")

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

        canvas.create_text(70, 250, text="LT", fill="white")
        canvas.create_rectangle(100, 240, 150, 260, outline="white")
        canvas.create_rectangle(100, 240, 100 + int(50 * state['axes']['LT']), 260, fill="red")

        canvas.create_text(250, 250, text="RT", fill="white")
        canvas.create_rectangle(280, 240, 330, 260, outline="white")
        canvas.create_rectangle(280, 240, 280 + int(50 * state['axes']['RT']), 260, fill="red")

        lx = 100 + int(state['axes']['LS_x'] * 20)
        ly = 200 + int(state['axes']['LS_y'] * 20)
        canvas.create_oval(lx-5, ly-5, lx+5, ly+5, fill="blue")

        rx = 300 + int(state['axes']['RS_x'] * 20)
        ry = 200 + int(state['axes']['RS_y'] * 20)
        canvas.create_oval(rx-5, ry-5, rx+5, ry+5, fill="blue")
        root.after(50, redraw)

    redraw()
    root.mainloop()

if __name__ == "__main__":
    threading.Thread(target=socket_thread, daemon=True).start()
    if SHOW_UI:
        run_ui()
    else:
        threading.Event().wait()