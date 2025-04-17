"""
This script implements a server that handles both UDP and TCP communication for a network-based application.

The server:
- Listens for incoming TCP connections on a specified port and handles client registration and disconnections.
- Accepts UDP audio packets from clients, forwards them to target clients based on a registered mapping, and manages client communication over UDP.
- Implements a heartbeat system that monitors connected clients to ensure they are alive, removing clients that time out after a specified period of inactivity.
- Provides a mechanism for clients to register with the server via a TCP handshake, specifying a target IP and port for forwarding UDP audio packets.

Key features:
- Handles a limited number of clients (up to MAX_CLIENTS).
- Ensures that client connections are managed with timeouts and heartbeats.
- Forwards audio data between clients over UDP based on TCP registration.
"""

# imports
import socket
import threading
import time
import select
import struct

# constants
TCP_IP = "0.0.0.0"  # IP address to bind for the TCP server
TCP_PORT = 8888  # Port for the TCP server to listen on
UDP_IP = "0.0.0.0"  # IP address to bind for the UDP server
UDP_PORT = 9999  # Port for the UDP server to listen on
BUFFER_SIZE = 2200  # Size of the buffer for receiving UDP data
MAX_CLIENTS = 10  # Maximum number of clients that can be connected at once
TCP_TIMEOUT = 30  # Timeout for TCP client connections in seconds
HEARTBEAT_TIMEOUT = 120  # Timeout for heartbeat in seconds, after which a client is considered dead
HEARTBEAT_INTERVAL = 10  # Interval to check the heartbeat of clients

"""
data structures for managing clients and heartbeats
"""
clients = {}  # A dictionary mapping client IPs to (listen_port, target_ip, target_port)
clients_lock = threading.Lock()  # Lock to protect the clients dictionary from race conditions
last_heartbeat = {}  # A dictionary mapping client IPs to their last heartbeat time
heartbeat_lock = threading.Lock()  # Lock to protect the heartbeat dictionary from race conditions

"""
Handles a UDP client by forwarding the received data to the appropriate target.
"""
def handle_client(data, addr):
    client_ip = addr[0]  # Get the client's IP address
    with clients_lock:
        if client_ip not in clients:
            print(f"Unregistered client {addr} sent data.")
            return  # If the client is not registered, ignore the data
        listen_port, target_ip, target_port = clients[client_ip]  # Get the client info from the dictionary
    if target_ip and target_port:
        try:
            # Forward the UDP data to the target IP and port
            server_socket.sendto(data, (target_ip, target_port))
            print(f"Forwarded packet from {client_ip} to {target_ip}:{target_port}")
        except Exception as e:
            print(f"Error forwarding to {target_ip}:{target_port}: {e}")

"""
Listens for incoming UDP audio packets and forwards them to the appropriate targets.
"""
def receive_audio():
    server_socket.setblocking(False)  # Set the UDP socket to non-blocking mode
    print("Started receiving UDP audio packets.")
    while True:
        try:
            # Use select to check for readable data on the socket with a timeout of 1 second
            readable, _, _ = select.select([server_socket], [], [], 1.0)
            if server_socket in readable:
                data, addr = server_socket.recvfrom(BUFFER_SIZE)  # Receive the UDP packet
                handle_client(data, addr)  # Handle the received data
        except socket.error as e:
            print(f"Error receiving data: {e}")
        except KeyboardInterrupt:
            print("Shutting down UDP receiver...")
            break

"""
Handles an incoming TCP client connection, processes messages like HELLO, HEARTBEAT, and DISCONNECT.
"""
def handle_tcp_client(tcp_conn, tcp_addr):
    try:
        tcp_conn.settimeout(TCP_TIMEOUT)  # Set the timeout for the TCP connection
        data = tcp_conn.recv(1024)  # Receive data from the TCP client
        if data.startswith(b"HELLO"):  # If the client sends a HELLO message
            # Parse HELLO: port (4 bytes) + target_ip (string)
            if len(data) < 9:
                print(f"Invalid HELLO from {tcp_addr}")
                tcp_conn.send(b"INVALID")  # Send an INVALID response if the data is too short
                return
            client_port = struct.unpack(">I", data[5:9])[0]  # Extract the client port (4 bytes)
            target_ip = data[9:].decode(errors="ignore")  # Extract the target IP as a string
            with clients_lock:
                if len(clients) < MAX_CLIENTS:
                    clients[tcp_addr[0]] = (client_port, target_ip, None)  # Register the client
                    # If the target IP is already registered, update the target port
                    if target_ip in clients:
                        target_port = clients[target_ip][0]  # Get the target port
                        clients[tcp_addr[0]] = (client_port, target_ip, target_port)
                        # Update reverse mapping if the target IP has the client IP as its target
                        if clients[target_ip][1] == tcp_addr[0]:
                            clients[target_ip] = (clients[target_ip][0], tcp_addr[0], client_port)
                    print(f"Client {tcp_addr[0]}:{client_port} registered, targeting {target_ip}")
                    tcp_conn.send(b"WELCOME")  # Send a WELCOME message to the client
                    with heartbeat_lock:
                        last_heartbeat[tcp_addr[0]] = time.time()  # Update the last heartbeat time for the client
                else:
                    print(f"Client limit reached. Rejecting {tcp_addr[0]}")
                    tcp_conn.send(b"FULL")  # Send a FULL response if the client limit is reached
        elif data == b"HEARTBEAT":  # If the client sends a HEARTBEAT message
            with heartbeat_lock:
                last_heartbeat[tcp_addr[0]] = time.time()  # Update the last heartbeat time
                tcp_conn.send(b"ALIVE")  # Send an ALIVE response to the client
                print(f"Heartbeat from {tcp_addr[0]}")
        elif data == b"DISCONNECT":  # If the client sends a DISCONNECT message
            with clients_lock:
                clients.pop(tcp_addr[0], None)  # Remove the client from the clients list
            with heartbeat_lock:
                last_heartbeat.pop(tcp_addr[0], None)  # Remove the client's heartbeat entry
            tcp_conn.send(b"BYE")  # Send a BYE response to the client
            print(f"Client {tcp_addr[0]} disconnected.")
        else:
            print(f"Invalid message from {tcp_addr}")
            tcp_conn.send(b"INVALID")  # Send an INVALID response if the message is unrecognized
    except socket.timeout:
        print(f"TCP timeout from {tcp_addr}")
        tcp_conn.send(b"TIMEOUT")  # Send a TIMEOUT message if the TCP connection times out
    except Exception as e:
        print(f"Error handling TCP client: {e}")
        tcp_conn.send(b"ERROR")  # Send an ERROR response in case of other exceptions
    finally:
        tcp_conn.close()  # Always close the TCP connection when done

"""
Listens for incoming TCP connections and spawns threads to handle them.
"""
def tcp_handshake_listener():
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.bind((TCP_IP, TCP_PORT))  # Bind the TCP socket to the specified IP and port
    tcp_socket.listen(5)  # Start listening for incoming connections (maximum 5 in the queue)
    print(f"TCP server listening on {TCP_IP}:{TCP_PORT}...")
    try:
        while True:
            tcp_conn, tcp_addr = tcp_socket.accept()  # Accept an incoming TCP connection
            threading.Thread(target=handle_tcp_client, args=(tcp_conn, tcp_addr)).start()  # Handle the connection in a separate thread
    except KeyboardInterrupt:
        print("Shutting down TCP listener...")
        tcp_socket.close()  # Close the TCP socket when the server is interrupted

"""
Monitors client heartbeats and disconnects clients that haven't sent a heartbeat in time.
"""
def heartbeat_monitor():
    while True:
        try:
            time.sleep(HEARTBEAT_INTERVAL)  # Wait for the next heartbeat interval
            current_time = time.time()  # Get the current time
            to_remove = []  # List of clients to remove due to timeout
            with heartbeat_lock:
                for client_ip, last_time in last_heartbeat.items():
                    if current_time - last_time > HEARTBEAT_TIMEOUT:  # If the client's heartbeat has timed out
                        to_remove.append(client_ip)  # Mark the client for removal
            with clients_lock:
                for client_ip in to_remove:
                    clients.pop(client_ip, None)  # Remove the client from the clients list
                    print(f"Client {client_ip} timed out.")
            with heartbeat_lock:
                for client_ip in to_remove:
                    last_heartbeat.pop(client_ip, None)  # Remove the client's heartbeat entry
        except KeyboardInterrupt:
            print("Shutting down heartbeat monitor...")
            break

"""
Main entry point for the server. Starts the UDP receiver, TCP listener, and heartbeat monitor.
"""
def main():
    global server_socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Create a UDP socket
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow reuse of address
    server_socket.bind(("0.0.0.0", UDP_PORT))  # Bind the UDP socket to the specified IP and port
    print(f"UDP server listening on {UDP_IP}:{UDP_PORT}...")
    try:
        threading.Thread(target=tcp_handshake_listener, daemon=True).start()  # Start the TCP listener in a separate thread
        threading.Thread(target=heartbeat_monitor, daemon=True).start()  # Start the heartbeat monitor in a separate thread
        receive_audio()  # Start receiving UDP audio packets
    except KeyboardInterrupt:
        print("Shutting down server...")
        server_socket.close()  # Close the UDP socket when the server is interrupted

if __name__ == "__main__":
    main()  # Run the main function to start the server