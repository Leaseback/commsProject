import sounddevice as sd
import numpy as np
import socket
import struct
import sys
import threading
import time

# Constants
SAMPLE_RATE = 44100  # Samples per second
CHANNELS = 1  # Mono audio
THRESHOLD = 0.05  # Silence threshold (adjust as needed)
CHUNK_SIZE = 1024  # Chunk size for sending data
UDP_IP = "127.0.0.1"  # Server IP (updated during runtime)
UDP_PORT = 9999  # Port to send UDP audio
TCP_PORT = 8888  # Port for TCP handshake
EOT_SEQ_NUM = 99999999  # End-of-transmission signal
HELLO_PACKET = b"HELLO"
WELCOME_PACKET = b"WELCOME"
HEARTBEAT_PACKET = b"HEARTBEAT"
TIMEOUT = 2  # Timeout for TCP in seconds
MAX_RETRIES = 3  # Maximum retries for TCP handshake
HEARTBEAT_INTERVAL = 30  # Heartbeat interval in seconds

# Create UDP socket for audio
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

is_recording = True
heartbeat_active = True


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
                tcp_sock.close()
                return True
            elif response == b"FULL":
                print("Server is full. Cannot connect.")
                tcp_sock.close()
                return False
            else:
                print("Unexpected response during handshake.")

        except (socket.timeout, ConnectionRefusedError) as e:
            print(f"Handshake failed: {e}")

        finally:
            tcp_sock.close()

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
            is_recording = False  # Stop sending audio packets if heartbeat fails
            sys.exit(1)
        finally:
            tcp_sock.close()

        time.sleep(HEARTBEAT_INTERVAL)


def record_and_send_audio():
    """Continuously records audio and sends packets over UDP every 20ms."""
    print("Recording and sending... Press Enter to stop and send EOT.")

    def callback(indata, frames, time, status):
        """Callback to process incoming audio data."""
        if status:
            print(status)

        # Convert audio to 16-bit PCM and bytes
        audio_bytes = (indata * 32767).astype(np.int16).tobytes()

        # Send audio in 882-sample chunks (20ms of audio)
        for i in range(0, len(audio_bytes), 882 * 2):  # 2 bytes per sample for 16-bit PCM
            chunk = audio_bytes[i:i + 882 * 2]  # 882 samples * 2 bytes/sample
            udp_sock.sendto(chunk, (UDP_IP, UDP_PORT))

    # Open the input stream and record continuously
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=callback):
        while is_recording:
            # Sleep to maintain 20ms intervals for sending packets
            sd.sleep(20)  # Sleep for 20ms (20ms * 44.1kHz = 882 samples)


def wait_for_exit():
    """Waits for the user to type 'quit' to stop sending audio and disconnect."""
    global is_recording, heartbeat_active
    while True:
        user_input = input().strip().lower()
        if user_input == "quit":
            print("\nDisconnecting from server and shutting down...")
            is_recording = False
            heartbeat_active = False
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
        audio_thread.start()

        # Start heartbeat in a separate thread
        heartbeat_thread = threading.Thread(target=send_heartbeat, args=(server_ip, TCP_PORT))
        heartbeat_thread.start()

        # Wait for quit command to quit program
        wait_for_exit()
    else:
        print("Failed to establish connection. Exiting.")
        sys.exit(1)


if __name__ == "__main__":
    main()
