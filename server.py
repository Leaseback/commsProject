import socket
import threading
import time

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
    if addr[0] not in [client[0] for client in clients]:
        print(f"Unregistered client {addr} attempted to send data.")
        return

    # Forward packets to all registered clients except sender
    with clients_lock:
        for client in clients:
            if client != addr:
                server_socket.sendto(data, client)


def receive_audio():
    """Receive audio packets from clients using UDP."""
    print("Started receiving UDP audio packets.")
    while True:
        try:
            data, addr = server_socket.recvfrom(BUFFER_SIZE)
            threading.Thread(target=handle_client, args=(data, addr)).start()
        except Exception as e:
            print(f"Error receiving data: {e}")


def handle_tcp_client(tcp_conn, tcp_addr):
    """Handle TCP handshake, heartbeats, and register the client for UDP communication."""
    global last_heartbeat

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

    while True:
        tcp_conn, tcp_addr = tcp_socket.accept()
        threading.Thread(target=handle_tcp_client, args=(tcp_conn, tcp_addr)).start()


def heartbeat_monitor():
    """Check for clients that have not sent a heartbeat within the timeout window."""
    global last_heartbeat, clients

    while True:
        time.sleep(HEARTBEAT_INTERVAL)  # Check every 10 seconds
        current_time = time.time()

        with heartbeat_lock:
            to_remove = []
            for client_ip, last_time in last_heartbeat.items():
                if current_time - last_time > HEARTBEAT_TIMEOUT:
                    print(f"Client {client_ip} timed out due to missed heartbeat.")
                    to_remove.append(client_ip)

            # Remove timed-out clients
            with clients_lock:
                for client_ip in to_remove:
                    clients = {c for c in clients if c[0] != client_ip}
                    del last_heartbeat[client_ip]  # Remove heartbeat tracking


def main():
    """Start the audio relay server with TCP handshake and heartbeat."""
    global server_socket

    # Create and bind the UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(("0.0.0.0", UDP_PORT))
    print(f"UDP audio server listening on {UDP_IP}:{UDP_PORT}...")

    # Start TCP handshake/heartbeat listener in a separate thread
    threading.Thread(target=tcp_handshake_listener, daemon=True).start()

    # Start heartbeat monitor in a separate thread
    threading.Thread(target=heartbeat_monitor, daemon=True).start()

    # Start receiving UDP audio packets
    receive_audio()


if __name__ == "__main__":
    main()
