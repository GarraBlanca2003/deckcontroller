import socket
import json
import pygame
import threading

SERVER_IP = "127.0.0.1"
SERVER_PORT = 5000

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((SERVER_IP, SERVER_PORT))

pygame.init()
pygame.joystick.init()

js = pygame.joystick.Joystick(0)
js.init()

def send(obj):
    sock.send(json.dumps(obj).encode())

def send_rumble(strength):
    send({"type": "rumble", "strength": strength})

def input_loop():
    while True:
        pygame.event.pump()

        # AXES
        send({"type": "axis", "axis": "LX", "value": js.get_axis(0)})
        send({"type": "axis", "axis": "LY", "value": js.get_axis(1)})
        send({"type": "axis", "axis": "RX", "value": js.get_axis(2)})
        send({"type": "axis", "axis": "RY", "value": js.get_axis(3)})

        # TRIGGERS (-1..1)
        send({"type": "trigger", "which": "LT", "value": js.get_axis(4)})
        send({"type": "trigger", "which": "RT", "value": js.get_axis(5)})

        # BUTTONS
        btns = {
            "A": 0, "B": 1, "X": 2, "Y": 3,
            "LB": 4, "RB": 5,
            "SELECT": 6, "START": 7,
            "L3": 8, "R3": 9,
        }
        for name, idx in btns.items():
            send({
                "type": "button",
                "btn": name,
                "pressed": js.get_button(idx)
            })

        pygame.time.wait(8)

threading.Thread(target=input_loop, daemon=True).start()

# OPTIONAL: keyboard to test rumble
print("Press number keys 1–9 for rumble strength")
while True:
    key = input()
    if key.isdigit():
        strength = int(key) / 9
        send_rumble(strength)
