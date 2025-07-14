import pygame
import socket
import json
import time
import sys
import tkinter as tk
from tkinter import simpledialog
import threading
from concurrent.futures import ThreadPoolExecutor
import ipaddress

SERVER_IP = ""
SERVER_PORT = 5000
CONFIG_PORT = 5001
DEBUG_PORT = 5002
RETRY_DELAY = 3
SCAN_TIMEOUT = 1

USE_RUMBLE = False
SEND_FULL_STATE = False
DEBUG = True

pygame.init()
pygame.display.set_caption("Input Sender")
screen = pygame.display.set_mode((1280, 800))
font = pygame.font.SysFont("monospace", 20)
clock = pygame.time.Clock()

def fetch_config_from_receiver():
    global USE_RUMBLE, SEND_FULL_STATE
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((SERVER_IP, CONFIG_PORT))
            data = s.recv(1024)
            config = json.loads(data.decode())
            USE_RUMBLE = config.get("RUMBLE", False)
            SEND_FULL_STATE = config.get("SEND_FULL_STATE", False)
            DEBUG = config.get("DEBUG", False)
            print(f"📡 Got config: rumble={USE_RUMBLE}, FullState={SEND_FULL_STATE}")
    except Exception as e:
        print("❌ Could not get config from receiver:", e)

def get_local_networks():
    networks = []
    try:
        hostname = socket.gethostname()
        local_ips = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for ip_info in local_ips:
            ip = ip_info[4][0]
            if not ip.startswith('127.'):
                network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
                networks.append(network)
    except Exception as e:
        print(f"Error getting local networks: {e}")
        networks = [
            ipaddress.IPv4Network("192.168.1.0/24"),
            ipaddress.IPv4Network("192.168.0.0/24"),
            ipaddress.IPv4Network("10.0.0.0/24"),
            ipaddress.IPv4Network("172.16.0.0/24"),
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
    print(f"🔍 Scanning {network}...")
    host_ips = [ip for ip in network.hosts()]
    total_ips = len(host_ips)
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(check_server_at_ip, ip): ip for ip in host_ips}
        completed = 0
        for future in futures:
            completed += 1
            if progress_callback:
                progress_callback(completed, total_ips, str(futures[future]))
            result = future.result()
            if result:
                print(f"✅ Found server at {result}!")
                return result
    return None

def scan_for_server():
    draw_status("Scanning LAN...")
    networks = get_local_networks()
    for network in networks:
        def progress_callback(completed, total, current_ip):
            percentage = (completed / total) * 100
            message = f"Scanning: {percentage:.0f}%"
            draw_status(message)
            pygame.display.flip()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
        server_ip = scan_network_range(network, progress_callback)
        if server_ip:
            return server_ip
    return None

def ask_for_ip():
    root = tk.Tk()
    root.withdraw()
    choice = simpledialog.askstring(
        "Server Discovery",
        "Enter 'scan' to search LAN automatically, or enter IP address manually:"
    )
    if not choice:
        return 'auto'
    choice = choice.strip().lower()
    return 'auto' if choice == 'scan' else choice

def connect():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SERVER_IP, SERVER_PORT))
            return s
        except socket.error:
            pygame.display.set_caption("Input Sender - Disconnected")
            draw_status("Connection error ")
            time.sleep(RETRY_DELAY)

def send(sock, payload):
    message = json.dumps(payload)
    try:
        sock.sendall((message + '\n').encode())
        buffer = ""
        while True:
            data = sock.recv(1024).decode()
            if not data:
                raise ConnectionError("Lost connection or no response")
            buffer += data
            if '\n' in buffer:
                line, _ = buffer.split('\n', 1)
                return json.loads(line)
                
    except socket.error:
        raise ConnectionError("Lost connection")
def debug_log(text):
    if DEBUG:
        try:
            with socket.create_connection((SERVER_IP, DEBUG_PORT)) as sock:
                sock.sendall(text.encode())
        except socket.error:
            raise ConnectionError("Lost connection")
def draw_status(message):
    screen.fill((20, 20, 20))
    label = font.render(message, True, (200, 200, 200))
    screen.blit(label, (20, 35))
    pygame.display.flip()

def rumble(rumble_power):
    if USE_RUMBLE:
        pass
        #debug_log(f"rumble : {rumble_power}")
        #pygame.joystick.Joystick.rumble(1,1,100)
def main():
    global SERVER_IP

    if not SERVER_IP or SERVER_IP.lower() == "auto":
        user_input = ask_for_ip() if not SERVER_IP else SERVER_IP
        SERVER_IP = scan_for_server() if user_input.lower() == 'auto' else user_input
        if not SERVER_IP:
            print("❌ No server found on LAN")
            sys.exit(1)

    fetch_config_from_receiver()

    pygame.joystick.init()
    while pygame.joystick.get_count() == 0:
        draw_status("🕹️ Waiting for controller...")
        time.sleep(1)
        pygame.joystick.quit()
        pygame.joystick.init()

    joystick = pygame.joystick.Joystick(0)
    joystick.init()

    axes_state = [0.0] * joystick.get_numaxes()
    buttons_state = [False] * joystick.get_numbuttons()
    hat_state = (0, 0)

    sock = connect()

    while True:
        try:
            pygame.event.pump()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sock.close()
                    sys.exit()

            if not pygame.display.get_active():
                draw_status("Paused (unfocused)")
                time.sleep(0.1)
                continue

            if SEND_FULL_STATE:
                axes = [round(joystick.get_axis(i), 2) for i in range(joystick.get_numaxes())]
                buttons = [joystick.get_button(i) for i in range(joystick.get_numbuttons())]
                hat = list(joystick.get_hat(0))
                if USE_RUMBLE:
                    response = send(sock, {
                        'type': 'full_state',
                        'data': {
                            'axes': axes,
                            'buttons': buttons,
                            'hat': hat
                        }
                    })
                    rumble(response["RUMBLE"])
                else:
                    send(sock, {
                        'type': 'full_state',
                        'data': {
                            'axes': axes,
                            'buttons': buttons,
                            'hat': hat
                        }
                    })
            else:
                for i in range(joystick.get_numaxes()):
                    val = round(joystick.get_axis(i), 2)
                    if abs(val - axes_state[i]) >= 0.01:
                        axes_state[i] = val
                        send(sock, {
                            'type': 'gamepad',
                            'data': { 'code': f"AXIS_{i}", 'state': val }
                        })

                for i in range(joystick.get_numbuttons()):
                    pressed = joystick.get_button(i)
                    if pressed != buttons_state[i]:
                        buttons_state[i] = pressed
                        send(sock, {
                            'type': 'gamepad',
                            'data': { 'code': f"BTN_{i}", 'state': pressed }
                        })

                new_hat = joystick.get_hat(0)
                if new_hat != hat_state:
                    hat_state = new_hat
                    send(sock, {
                        'type': 'gamepad',
                        'data': { 'code': "HAT_0", 'state': list(hat_state) }
                    })
                
            if USE_RUMBLE:
                draw_status(f"RUMBLE: {rumble}")
            else:
                draw_status("")

            clock.tick(60)

        except (ConnectionError, BrokenPipeError):
            print("⚠️ Lost connection. Reconnecting...")
            draw_status("Disconnected, retrying...")
            time.sleep(0.5)
            sock.close()
            sock = connect()

if __name__ == "__main__":
    main()
