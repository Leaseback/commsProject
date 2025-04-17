import socket
import threading
import time
import select
import struct

# Constants
TCP_IP = "0.0.0.0"
TCP_PORT = 8888
UDP_IP = "0.0.0.0"
UDP_PORT = 9999
BUFFER_SIZE = 2200
MAX_CLIENTS = 10
TCP_TIMEOUT = 30
HEARTBEAT_TIMEOUT = 120
HEARTBEAT_INTERVAL = 10

# Map client_ip to (listen_port, target_ip, target_port)
clients = {}
clients_lock = threading.Lock()
last_heartbeat = {}
heartbeat_lock = threading.Lock()

def handle_client(data, addr):
    client_ip = addr[0]
    with clients_lock:
        if client_ip not in clients:
            print(f"Unregistered client {addr} sent data.")
            return
        listen_port, target_ip, target_port = clients[client_ip]
    if target_ip and target_port:
        try:
            server_socket.sendto(data, (target_ip, target_port))
            print(f"Forwarded packet from {client_ip} to {target_ip}:{target_port}")
        except Exception as e:
            print(f"Error forwarding to {target_ip}:{target_port}: {e}")

def receive_audio():
    server_socket.setblocking(False)
    print("Started receiving UDP audio packets.")
    while True:
        try:
            readable, _, _ = select.select([server_socket], [], [], 1.0)
            if server_socket in readable:
                data, addr = server_socket.recvfrom(BUFFER_SIZE)
                handle_client(data, addr)
        except socket.error as e:
            print(f"Error receiving data: {e}")
        except KeyboardInterrupt:
            print("Shutting down UDP receiver...")
            break

def handle_tcp_client(tcp_conn, tcp_addr):
    try:
        tcp_conn.settimeout(TCP_TIMEOUT)
        data = tcp_conn.recv(1024)
        if data.startswith(b"HELLO"):
            # Parse HELLO: port (4 bytes) + target_ip (string)
            if len(data) < 9:
                print(f"Invalid HELLO from {tcp_addr}")
                tcp_conn.send(b"INVALID")
                return
            client_port = struct.unpack(">I", data[5:9])[0]
            target_ip = data[9:].decode(errors="ignore")
            with clients_lock:
                if len(clients) < MAX_CLIENTS:
                    clients[tcp_addr[0]] = (client_port, target_ip, None)
                    # Update target_port if target_ip is registered
                    if target_ip in clients:
                        target_port = clients[target_ip][0]
                        clients[tcp_addr[0]] = (client_port, target_ip, target_port)
                        # Update reverse mapping
                        if clients[target_ip][1] == tcp_addr[0]:
                            clients[target_ip] = (clients[target_ip][0], tcp_addr[0], client_port)
                    print(f"Client {tcp_addr[0]}:{client_port} registered, targeting {target_ip}")
                    tcp_conn.send(b"WELCOME")
                    with heartbeat_lock:
                        last_heartbeat[tcp_addr[0]] = time.time()
                else:
                    print(f"Client limit reached. Rejecting {tcp_addr[0]}")
                    tcp_conn.send(b"FULL")
        elif data == b"HEARTBEAT":
            with heartbeat_lock:
                last_heartbeat[tcp_addr[0]] = time.time()
                tcp_conn.send(b"ALIVE")
                print(f"Heartbeat from {tcp_addr[0]}")
        elif data == b"DISCONNECT":
            with clients_lock:
                clients.pop(tcp_addr[0], None)
            with heartbeat_lock:
                last_heartbeat.pop(tcp_addr[0], None)
            tcp_conn.send(b"BYE")
            print(f"Client {tcp_addr[0]} disconnected.")
        else:
            print(f"Invalid message from {tcp_addr}")
            tcp_conn.send(b"INVALID")
    except socket.timeout:
        print(f"TCP timeout from {tcp_addr}")
        tcp_conn.send(b"TIMEOUT")
    except Exception as e:
        print(f"Error handling TCP client: {e}")
        tcp_conn.send(b"ERROR")
    finally:
        tcp_conn.close()

def tcp_handshake_listener():
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.bind((TCP_IP, TCP_PORT))
    tcp_socket.listen(5)
    print(f"TCP server listening on {TCP_IP}:{TCP_PORT}...")
    try:
        while True:
            tcp_conn, tcp_addr = tcp_socket.accept()
            threading.Thread(target=handle_tcp_client, args=(tcp_conn, tcp_addr)).start()
    except KeyboardInterrupt:
        print("Shutting down TCP listener...")
        tcp_socket.close()

def heartbeat_monitor():
    while True:
        try:
            time.sleep(HEARTBEAT_INTERVAL)
            current_time = time.time()
            to_remove = []
            with heartbeat_lock:
                for client_ip, last_time in last_heartbeat.items():
                    if current_time - last_time > HEARTBEAT_TIMEOUT:
                        to_remove.append(client_ip)
            with clients_lock:
                for client_ip in to_remove:
                    clients.pop(client_ip, None)
                    print(f"Client {client_ip} timed out.")
            with heartbeat_lock:
                for client_ip in to_remove:
                    last_heartbeat.pop(client_ip, None)
        except KeyboardInterrupt:
            print("Shutting down heartbeat monitor...")
            break

def main():
    global server_socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("0.0.0.0", UDP_PORT))
    print(f"UDP server listening on {UDP_IP}:{UDP_PORT}...")
    try:
        threading.Thread(target=tcp_handshake_listener, daemon=True).start()
        threading.Thread(target=heartbeat_monitor, daemon=True).start()
        receive_audio()
    except KeyboardInterrupt:
        print("Shutting down server...")
        server_socket.close()

if __name__ == "__main__":
    main()
    