import socket
import threading
import time
import select

# Constants
TCP_IP = "0.0.0.0"  # Listen on all interfaces for TCP
TCP_PORT = 8888  # Port for TCP handshakes and heartbeats
UDP_IP = "0.0.0.0"  # Listen on all interfaces for UDP
UDP_PORT = 9999  # Port for UDP audio data
BUFFER_SIZE = 2200  # Size of audio packets
EOT_SEQ_NUM = 99999999  # End-of-transmission signal
MAX_CLIENTS = 10  # Maximum number of connected clients
TCP_TIMEOUT = 30  # Timeout for TCP handshake (in seconds)
HEARTBEAT_TIMEOUT = 120  # Timeout in seconds before client is disconnected
HEARTBEAT_INTERVAL = 10  # How often to check for client heartbeats

# Store connected clients (IP, UDP_PORT)
clients = set()
clients_lock = threading.Lock()

# Track the last heartbeat time for each client
last_heartbeat = {}
heartbeat_lock = threading.Lock()


def handle_client(data, addr):
    """Handle audio packets from one client and forward to others."""
    # Ignore packets from unregistered clients
    if (addr[0], UDP_PORT) not in clients:
        print(f"Unregistered client {addr} attempted to send data.")
        return

    # Forward packets to all registered clients except sender
    with clients_lock:
        for client in clients:
            if client != (addr[0], UDP_PORT):
                server_socket.sendto(data, client)


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
    """Handle TCP handshake, heartbeats, and register the client for UDP communication."""
    # global last_heartbeat

    try:
        tcp_conn.settimeout(TCP_TIMEOUT)  # Set TCP timeout for handshake
        data = tcp_conn.recv(1024)

        if data == b"HELLO":  # Basic handshake message
            with clients_lock:
                if len(clients) < MAX_CLIENTS:
                    # Add client IP to the set (register the client)
                    clients.add((tcp_addr[0], UDP_PORT))  # Store IP address, ignore port
                    print(f"Client {tcp_addr[0]} registered successfully.")
                    tcp_conn.send(b"WELCOME")  # Send handshake success
                    # Initialize last heartbeat time for this client
                    with heartbeat_lock:
                        last_heartbeat[tcp_addr[0]] = time.time()
                else:
                    print(f"Client limit reached. Rejecting {tcp_addr[0]}")
                    tcp_conn.send(b"FULL")  # Send failure if max clients reached

        elif data == b"HEARTBEAT":  # Handle heartbeat messages
            with heartbeat_lock:
                last_heartbeat[tcp_addr[0]] = time.time()
                tcp_conn.send(b"ALIVE")  # Acknowledge the heartbeat
                print(f"Heartbeat received from {tcp_addr[0]}")
        elif data == b"DISCONNECT":
            with clients_lock:
                clients.discard((tcp_addr[0], UDP_PORT))
            with heartbeat_lock:
                last_heartbeat.pop(tcp_addr[0], None)
            tcp_conn.send(b"BYE")
            print(f"Client {tcp_addr[0]} disconnected gracefully.")

        else:
            print(f"Invalid handshake or message from {tcp_addr}")
            tcp_conn.send(b"INVALID")

    except socket.timeout:
        print(f"TCP handshake timeout from {tcp_addr}")
        tcp_conn.send(b"TIMEOUT")
    except Exception as e:
        print(f"Error handling TCP client: {e}")
        tcp_conn.send(b"ERROR")
    finally:
        tcp_conn.close()


def tcp_handshake_listener():
    """Listen for TCP handshakes and heartbeats to register and monitor clients."""
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.bind((TCP_IP, TCP_PORT))
    tcp_socket.listen(5)
    print(f"TCP handshake and heartbeat server listening on {TCP_IP}:{TCP_PORT}...")
    try:
        while True:
            tcp_conn, tcp_addr = tcp_socket.accept()
            threading.Thread(target=handle_tcp_client, args=(tcp_conn, tcp_addr)).start()
    except KeyboardInterrupt:
        print("Shutting down TCP listener...")
        tcp_socket.close()


def heartbeat_monitor():
    """Check for clients that have not sent a heartbeat within the timeout window."""
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
                    clients.discard((client_ip, UDP_PORT))
                    print(f"Client {client_ip} timed out due to missed heartbeat.")
                    last_heartbeat.pop(client_ip, None)
        except KeyboardInterrupt:
            print("Shutting down heartbeat monitor...")
            break


def main():
    """Start the audio relay server with TCP handshake and heartbeat."""
    global server_socket

    # Create and bind the UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(("0.0.0.0", UDP_PORT))
    print(f"UDP audio server listening on {UDP_IP}:{UDP_PORT}...")

    try:
        # Start TCP handshake/heartbeat listener in a separate thread
        threading.Thread(target=tcp_handshake_listener, daemon=True).start()

        # Start heartbeat monitor in a separate thread
        threading.Thread(target=heartbeat_monitor, daemon=True).start()

        # Start receiving UDP audio packets
        receive_audio()
    except KeyboardInterrupt:
        print("Shutting down server...")
        server_socket.close()


if __name__ == "__main__":
    main()
