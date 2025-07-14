
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 5002))
    server.listen(1)
    print(f"[DEBUG] Listening on {5002}...")
    conn, addr = server.accept()
    with conn:
        print(f"[DEBUG] Connected by {addr}")
        buffer = ""
        while True:
            data = conn.recv(1024)
            if not data:
                print("[DEBUG] Connection closed.")
                break
            buffer += data.decode()
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                print(f"[DEBUG] {line}")