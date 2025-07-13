import socket
import json
import threading
import vgamepad as vg

SHOW_UI = False

gamepad = vg.VX360Gamepad()

button_map = {
    'BTN_0': vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    'BTN_1': vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    'BTN_2': vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    'BTN_3': vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    'BTN_4': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    'BTN_5': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    'BTN_6': vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    'BTN_7': vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    'BTN_9': vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    'BTN_10': vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB
}

axis_state = {
    'LS_x': 0, 'LS_y': 0,
    'RS_x': 0, 'RS_y': 0,
    'LT': 0, 'RT': 0
}

pressed_buttons = set()

dpad_state = {
    'up': False,
    'down': False,
    'left': False,
    'right': False
}

def update_dpad():
    vertical = None
    horizontal = None

    if dpad_state['up'] and not dpad_state['down']:
        vertical = 'up'
    elif dpad_state['down'] and not dpad_state['up']:
        vertical = 'down'

    if dpad_state['left'] and not dpad_state['right']:
        horizontal = 'left'
    elif dpad_state['right'] and not dpad_state['left']:
        horizontal = 'right'

    direction = vg.DPAD_DIRECTION.DPAD_OFF

    if vertical == 'up' and horizontal == 'left':
        direction = vg.DPAD_DIRECTION.DPAD_UP_LEFT
    elif vertical == 'up' and horizontal == 'right':
        direction = vg.DPAD_DIRECTION.DPAD_UP_RIGHT
    elif vertical == 'down' and horizontal == 'left':
        direction = vg.DPAD_DIRECTION.DPAD_DOWN_LEFT
    elif vertical == 'down' and horizontal == 'right':
        direction = vg.DPAD_DIRECTION.DPAD_DOWN_RIGHT
    elif vertical == 'up':
        direction = vg.DPAD_DIRECTION.DPAD_UP
    elif vertical == 'down':
        direction = vg.DPAD_DIRECTION.DPAD_DOWN
    elif horizontal == 'left':
        direction = vg.DPAD_DIRECTION.DPAD_LEFT
    elif horizontal == 'right':
        direction = vg.DPAD_DIRECTION.DPAD_RIGHT

    gamepad.dpad(direction)
    gamepad.update()

def handle_event(code, value):
    global axis_state, pressed_buttons

    if code.startswith("BTN_"):
        btn = button_map.get(code)
        if btn:
            if value:
                gamepad.press_button(btn)
                pressed_buttons.add(btn)
            else:
                gamepad.release_button(btn)
                pressed_buttons.discard(btn)
            gamepad.update()

    elif code.startswith("HAT_0_"):
        direction = code.split("_")[-1].lower()
        if direction in dpad_state:
            dpad_state[direction] = bool(value)
        update_dpad()

    elif code.startswith("AXIS_"):
        val = int(value * 32767)
        if code == "AXIS_0":
            axis_state['LS_x'] = val
        elif code == "AXIS_1":
            axis_state['LS_y'] = -val
        elif code == "AXIS_3":
            axis_state['RS_x'] = val
        elif code == "AXIS_4":
            axis_state['RS_y'] = -val
        elif code == "AXIS_2":
            axis_state['LT'] = int((value + 1) / 2 * 255)
        elif code == "AXIS_5":
            axis_state['RT'] = int((value + 1) / 2 * 255)

        gamepad.left_joystick(x_value=axis_state['LS_x'], y_value=axis_state['LS_y'])
        gamepad.right_joystick(x_value=axis_state['RS_x'], y_value=axis_state['RS_y'])
        gamepad.left_trigger(value=axis_state['LT'])
        gamepad.right_trigger(value=axis_state['RT'])
        gamepad.update()

def socket_thread():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 5000))
    sock.listen(1)
    print("🎮 Waiting for deck...")

    while True:
        try:
            conn, addr = sock.accept()
            print(f"✅ Connected from {addr}")

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
    # No UI for Windows in this version
    pass

if __name__ == "__main__":
    threading.Thread(target=socket_thread, daemon=True).start()
    if SHOW_UI:
        run_ui()
    else:
        threading.Event().wait()
