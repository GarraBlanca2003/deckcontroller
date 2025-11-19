import pygame
import socket
import json
import time
import sys
import tkinter as tk
from tkinter import simpledialog
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import ctypes

# =========================================================
# WINDOWS SOCKET POPUP SUPPRESSION
# =========================================================
if sys.platform.startswith("win"):
    ctypes.windll.kernel32.SetErrorMode(0x0002)

SERVER_IP = ""
SERVER_PORT = 5000
CONFIG_PORT = 5001
RETRY_DELAY = 3
SCAN_TIMEOUT = 0.4

USE_RUMBLE = False
SEND_FULL_STATE = True
DEBUG = True

# =========================================================
# TKINTER MUST INIT BEFORE PYGAME ON WINDOWS
# =========================================================
root = tk.Tk()
root.withdraw()

# =========================================================
# PYGAME INIT
# =========================================================
pygame.init()
pygame.display.set_caption("Input Sender")
screen = pygame.display.set_mode((1280, 800))
font = pygame.font.SysFont("monospace", 20)
clock = pygame.time.Clock()


# =========================================================
# CONFIG FETCHING
# =========================================================
def fetch_config_from_receiver():
    global USE_RUMBLE, SEND_FULL_STATE, DEBUG
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((SERVER_IP, CONFIG_PORT))
            data = s.recv(1024)
            config = json.loads(data.decode())
            #USE_RUMBLE = config.get("RUMBLE", False)
            SEND_FULL_STATE = config.get("SEND_FULL_STATE", False)
            DEBUG = config.get("DEBUG", False)
            print(f"Config fetched: rumble={USE_RUMBLE} full_state={SEND_FULL_STATE}")
    except Exception as e:
        print("Could not retrieve config:", e)


# =========================================================
# NETWORK DISCOVERY
# =========================================================
def get_local_networks():
    networks = []
    try:
        name, alias, addrs = socket.gethostbyname_ex(socket.gethostname())
        for ip in addrs:
            if not ip.startswith("127."):
                networks.append(ipaddress.IPv4Network(f"{ip}/24", strict=False))
    except:
        networks = [
            ipaddress.IPv4Network("192.168.1.0/24"),
            ipaddress.IPv4Network("192.168.0.0/24"),
            ipaddress.IPv4Network("10.0.0.0/24"),
        ]
    return networks


def check_server_at_ip(ip):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SCAN_TIMEOUT)
        result = sock.connect_ex((str(ip), SERVER_PORT))
        sock.close()
        return str(ip) if result == 0 else None
    except:
        return None


def scan_network_range(network, progress_callback=None):
    print(f"Scanning {network}...")
    hosts = list(network.hosts())
    total = len(hosts)

    with ThreadPoolExecutor(max_workers=80) as executor:
        futures = {executor.submit(check_server_at_ip, ip): ip for ip in hosts}
        completed = 0

        for future in futures:
            completed += 1

            if progress_callback:
                progress_callback(completed, total, str(futures[future]))

            result = future.result()
            if result:
                print(f"SERVER FOUND at {result}")
                return result

    return None


def scan_for_server():
    draw_status("Scanning LAN...")
    pygame.display.flip()
    networks = get_local_networks()

    for network in networks:

        def progress(c, t, ip):
            pct = (c / t) * 100
            draw_status(f"Scanning {ip}  {pct:.0f}%")
            pygame.display.flip()

        found = scan_network_range(network, progress)
        if found:
            return found

    return None


def ask_for_ip():
    answer = simpledialog.askstring(
        "Server Discovery",
        "Enter 'scan' for auto-scan or enter IP manually:"
    )
    if not answer:
        return "auto"
    return "auto" if answer.lower().strip() == "scan" else answer.strip()


# =========================================================
# COMMUNICATION HELPERS
# =========================================================
def connect():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SERVER_IP, SERVER_PORT))
            return s
        except:
            pygame.display.set_caption("Input Sender - Disconnected")
            draw_status("Connection failed, retrying...")
            time.sleep(RETRY_DELAY)


def send(sock, payload):
    msg = json.dumps(payload) + "\n"
    try:
        sock.sendall(msg.encode())
        buffer = ""
        while True:
            data = sock.recv(1024).decode()
            if not data:
                raise ConnectionError("Disconnected")
            buffer += data
            if "\n" in buffer:
                line, _ = buffer.split("\n", 1)
                return json.loads(line)
    except:
        raise ConnectionError("Lost connection")


def debug_log(sock, text):
    if DEBUG:
        send(sock, {"type": "debug", "data": text})


def draw_status(text):
    screen.fill((20, 20, 20))
    label = font.render(text, True, (200, 200, 200))
    screen.blit(label, (20, 35))
    pygame.display.flip()


def rumble(sock, strength):
    if USE_RUMBLE:
        debug_log(sock, f"rumble {strength}")


# =========================================================
# MAIN PROGRAM
# =========================================================
def main():
    global SERVER_IP

    # Ask user
    if not SERVER_IP or SERVER_IP.lower() == "auto":
        selection = ask_for_ip()
        SERVER_IP = scan_for_server() if selection == "auto" else selection

        if not SERVER_IP:
            print("No server found.")
            sys.exit(1)

    fetch_config_from_receiver()

    pygame.joystick.init()
    while pygame.joystick.get_count() == 0:
        draw_status("Waiting for controller...")
        pygame.time.wait(500)
        pygame.joystick.quit()
        pygame.joystick.init()

    joystick = pygame.joystick.Joystick(0)
    joystick.init()

    axes_state = [0] * joystick.get_numaxes()
    buttons_state = [0] * joystick.get_numbuttons()

    # Hat-safe initialization (Windows controllers often have 0 hats)
    hat_count = joystick.get_numhats()
    hat_state = (0, 0) if hat_count > 0 else None

    sock = connect()

    # =========================================================
    # GAME LOOP
    # =========================================================
    while True:
        try:
            pygame.event.pump()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit()
                    sock.close()
                    sys.exit()

            # -------------------------
            # SEND FULL STATE
            # -------------------------
            if SEND_FULL_STATE:

                axes = [round(joystick.get_axis(i), 2)
                        for i in range(joystick.get_numaxes())]
                buttons = [joystick.get_button(i)
                           for i in range(joystick.get_numbuttons())]

                if hat_count > 0:
                    hat = list(joystick.get_hat(0))
                else:
                    hat = [0, 0]

                if USE_RUMBLE:
                    response = send(sock, {
                        "type": "full_state",
                        "data": {"axes": axes, "buttons": buttons, "hat": hat}
                    })
                    #print(f"using rumble Rumble status :{USE_RUMBLE}")
                    rumble(sock, response.get("RUMBLE", 0))
                else:
                    send(sock, {
                        "type": "full_state",
                        "data": {"axes": axes, "buttons": buttons, "hat": hat}
                    })
                    print({"type": "full_state","data": {"axes": axes, "buttons": buttons,"hat": hat}})

            # -------------------------
            # SEND ONLY CHANGES
            # -------------------------
            else:
                # Axes
                for i in range(joystick.get_numaxes()):
                    val = round(joystick.get_axis(i), 2)
                    if abs(val - axes_state[i]) >= 0.01:
                        axes_state[i] = val
                        send(sock, {
                            "type": "gamepad",
                            "data": {"code": f"AXIS_{i}", "state": val}
                        })

                # Buttons
                for i in range(joystick.get_numbuttons()):
                    st = joystick.get_button(i)
                    if st != buttons_state[i]:
                        buttons_state[i] = st
                        send(sock, {
                            "type": "gamepad",
                            "data": {"code": f"BTN_{i}", "state": st}
                        })

                # Hat (safe mode — only read if controller HAS a hat)
                if hat_count > 0:
                    new_hat = joystick.get_hat(0)
                    if new_hat != hat_state:
                        hat_state = new_hat
                        send(sock, {
                            "type": "gamepad",
                            "data": {"code": "HAT_0", "state": list(hat_state)}
                        })

            draw_status("")
            clock.tick(60)

        except ConnectionError:
            draw_status("Reconnecting...")
            time.sleep(0.3)
            sock.close()
            sock = connect()


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":
    main()
