import socket
import threading

# Constants
UDP_IP = "0.0.0.0"  # Listen on all interfaces
UDP_PORT = 9999  # Port to receive audio data
BUFFER_SIZE = 1024  # Size of audio packets
EOT_SEQ_NUM = 99999999  # End-of-transmission signal
MAX_CLIENTS = 10  # Maximum number of connected clients

# Store connected clients
clients = set()
clients_lock = threading.Lock()


def handle_client(data, addr):
    """Handle audio packets from one client and forward to others."""
    with clients_lock:
        # Add client if not already in the set
        if addr not in clients:
            clients.add(addr)
            print(f"New client connected: {addr}")

    # Check if EOT received
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
    """Receive audio packets from clients."""
    while True:
        data, addr = server_socket.recvfrom(BUFFER_SIZE)
        threading.Thread(target=handle_client, args=(data, addr)).start()


def main():
    """Start the audio relay server."""
    global server_socket

    # Create and bind the UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((UDP_IP, UDP_PORT))

    print(f"Server listening on {UDP_IP}:{UDP_PORT}...")

    # Start receiving audio packets
    receive_audio()


if __name__ == "__main__":
    main()
