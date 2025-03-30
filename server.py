import socket
import threading

# Constants
TCP_IP = "0.0.0.0"  # Listen on all interfaces for TCP
TCP_PORT = 8888  # Port for TCP handshakes
UDP_IP = "0.0.0.0"  # Listen on all interfaces for UDP
UDP_PORT = 9999  # Port for UDP audio data
BUFFER_SIZE = 1024  # Size of audio packets
EOT_SEQ_NUM = 99999999  # End-of-transmission signal
MAX_CLIENTS = 10  # Maximum number of connected clients

# Store connected clients (only by IP, no port tracking)
clients = set()
clients_lock = threading.Lock()


def handle_client(data, addr):
    """Handle audio packets from one client and forward to others."""
    with clients_lock:
        # Ignore packets from unregistered clients
        if addr[0] not in [client[0] for client in clients]:
            print(f"Unregistered client {addr} attempted to send data.")
            return

    # Check if EOT (End-of-Transmission) received
    if len(data) == 4:
        seq_num = int.from_bytes(data, byteorder="big")
        if seq_num == EOT_SEQ_NUM:
            print(f"EOT received from {addr}. Removing client.")
            with clients_lock:
                clients.discard(addr)
            return

    # Forward audio to all other connected clients
    with clients_lock:
        for client in clients:
            if client != addr:
                server_socket.sendto(data, client)


def receive_audio():
    """Receive audio packets from clients using UDP."""
    while True:
        data, addr = server_socket.recvfrom(BUFFER_SIZE)
        threading.Thread(target=handle_client, args=(data, addr)).start()


def handle_tcp_client(tcp_conn, tcp_addr):
    """Handle TCP handshake and register the client for UDP communication."""
    try:
        data = tcp_conn.recv(1024)
        if data == b"HELLO":  # Basic handshake message
            with clients_lock:
                if len(clients) < MAX_CLIENTS:
                    # Add client IP to the set (register the client)
                    clients.add((tcp_addr[0], UDP_PORT))  # Store IP address, ignore port
                    print(f"Client {tcp_addr[0]} registered successfully.")
                    tcp_conn.send(b"WELCOME")  # Send handshake success
                else:
                    print(f"Client limit reached. Rejecting {tcp_addr[0]}")
                    tcp_conn.send(b"FULL")  # Send failure if max clients reached
        else:
            print(f"Invalid handshake from {tcp_addr}")
    except Exception as e:
        print(f"Error handling TCP client: {e}")
    finally:
        tcp_conn.close()


def tcp_handshake_listener():
    """Listen for TCP handshakes to register clients."""
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.bind((TCP_IP, TCP_PORT))
    tcp_socket.listen(5)
    print(f"TCP handshake server listening on {TCP_IP}:{TCP_PORT}...")

    while True:
        tcp_conn, tcp_addr = tcp_socket.accept()
        threading.Thread(target=handle_tcp_client, args=(tcp_conn, tcp_addr)).start()


def main():
    """Start the audio relay server with TCP handshake."""
    global server_socket

    # Create and bind the UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((UDP_IP, UDP_PORT))
    print(f"UDP audio server listening on {UDP_IP}:{UDP_PORT}...")

    # Start TCP handshake listener in a separate thread
    threading.Thread(target=tcp_handshake_listener, daemon=True).start()

    # Start receiving UDP audio packets
    receive_audio()


if __name__ == "__main__":
    main()
