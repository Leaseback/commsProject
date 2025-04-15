import sounddevice as sd
import numpy as np
import socket
import struct
import sys
import threading
import time

# Constants
SAMPLE_RATE = 44100
CHANNELS = 1
THRESHOLD = 0.05
CHUNK_SIZE = 882  # Samples per packet (20ms at 44100Hz)
BYTES_PER_PACKET = CHUNK_SIZE * 2  # 1764 bytes for 16-bit mono PCM
UDP_IP = "127.0.0.1"
UDP_PORT = 9999
TCP_PORT = 8888
EOT_SEQ_NUM = 99999999
HELLO_PACKET = b"HELLO"
WELCOME_PACKET = b"WELCOME"
HEARTBEAT_PACKET = b"HEARTBEAT"
TIMEOUT = 2
MAX_RETRIES = 3
HEARTBEAT_INTERVAL = 30

# Create UDP socket for audio
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

is_recording = True
heartbeat_active = True
sequence_number = 0  # Global sequence number for packets

def tcp_handshake(server_ip, tcp_port):
    """Perform TCP handshake with the server."""
    for attempt in range(MAX_RETRIES):
        try:
            print(f"Attempting TCP handshake with {server_ip}:{tcp_port} (Attempt {attempt + 1})...")

            # Create TCP socket for handshake
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.settimeout(TIMEOUT)

            # Connect to the server
            tcp_sock.connect((server_ip, tcp_port))

            # Send HELLO packet
            tcp_sock.send(HELLO_PACKET)
            response = tcp_sock.recv(1024)

            # Check server's response
            if response == WELCOME_PACKET:
                print("Handshake successful! Ready to send audio.")
                return True
            elif response == b"FULL":
                print("Server is full. Cannot connect.")
                return False
            else:
                print("Unexpected response during handshake.")
        except (socket.timeout, ConnectionRefusedError) as e:
            print(f"Handshake failed: {e}")
        finally:
            try:
                tcp_sock.close()
            except:
                pass
    print("Handshake failed after maximum retries.")
    return False

def send_heartbeat(server_ip, tcp_port):
    """Sends a TCP heartbeat packet every 30 seconds."""
    global heartbeat_active, is_recording
    while heartbeat_active:
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.settimeout(TIMEOUT)
            tcp_sock.connect((server_ip, tcp_port))

            # Send HEARTBEAT packet
            tcp_sock.send(HEARTBEAT_PACKET)
            response = tcp_sock.recv(1024)

            if response == b"ALIVE":
                print("Heartbeat acknowledged by server.")
            else:
                print("Unexpected response to heartbeat.")
        except (socket.timeout, ConnectionRefusedError):
            print("Heartbeat failed. Server may be offline.")
            is_recording = False
            heartbeat_active = False
            return
        finally:
            try:
                tcp_sock.close()
            except:
                pass
        time.sleep(HEARTBEAT_INTERVAL)

def record_and_send_audio():
    """Continuously records audio and sends packets over UDP every 20ms."""
    global sequence_number, is_recording
    print("Recording and sending... Press Enter to stop and send EOT.")

    def callback(indata, frames, time, status):
        """Callback to process incoming audio data."""
        global sequence_number
        if status:
            print(status)
        if not is_recording:
            return

        # Convert audio to 16-bit PCM
        audio_data = (indata * 32767).astype(np.int16)
        audio_bytes = audio_data.tobytes()

        # Send audio in 882-sample chunks (20ms)
        for i in range(0, len(audio_bytes), BYTES_PER_PACKET):
            chunk = audio_bytes[i:i + BYTES_PER_PACKET]
            if len(chunk) == BYTES_PER_PACKET:  # Ensure full packet
                # Prepend 4-byte sequence number
                packet = struct.pack(">I", sequence_number) + chunk
                udp_sock.sendto(packet, (UDP_IP, UDP_PORT))
                sequence_number += 1

    # Open input stream
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=CHUNK_SIZE, callback=callback):
        while is_recording:
            # Sleep to maintain 20ms intervals for sending packets
            sd.sleep(20)  # Sleep for 20ms (20ms * 44.1kHz = 882 samples)

def send_eot():
    """Send end-of-transmission packet."""
    eot_packet = struct.pack(">I", EOT_SEQ_NUM) + b"\x00" * BYTES_PER_PACKET
    udp_sock.sendto(eot_packet, (UDP_IP, UDP_PORT))
    print("Sent EOT packet.")

def wait_for_exit():
    """Waits for the user to type 'quit' to stop sending audio and disconnect."""
    global is_recording, heartbeat_active
    while True:
        user_input = input().strip().lower()
        if user_input == "quit":
            print("\nDisconnecting from server and shutting down...")
            is_recording = False
            send_eot()
            heartbeat_active = False
            time.sleep(0.1)  # Allow EOT to send
            udp_sock.close()
            sys.exit(0)
        else:
            print("Type 'quit' to stop and send EOT.")


def main():
    global UDP_IP
    """Main entry point for the audio client."""
    if len(sys.argv) < 2:
        print("Usage: python Audio.py <server_ip>")
        sys.exit(1)

    server_ip = sys.argv[1]  # Get the server IP from command line argument
    UDP_IP = server_ip  # Set the server IP for UDP

    # Perform TCP handshake before starting audio
    if tcp_handshake(server_ip, TCP_PORT):
        # Start audio recording and sending in a separate thread
        audio_thread = threading.Thread(target=record_and_send_audio)
        audio_thread.daemon = True
        audio_thread.start()

        # Start heartbeat in a separate thread
        heartbeat_thread = threading.Thread(target=send_heartbeat, args=(server_ip, TCP_PORT))
        heartbeat_thread.daemon = True
        heartbeat_thread.start()

        # Wait for quit command to quit program
        wait_for_exit()
    else:
        print("Failed to establish connection. Exiting.")
        sys.exit(1)


if __name__ == "__main__":
    main()
