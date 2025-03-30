import sounddevice as sd
import numpy as np
import socket
import struct
import sys

# Constants
SAMPLE_RATE = 44100  # Samples per second
CHANNELS = 1  # Mono audio
THRESHOLD = 0.05  # Silence threshold (adjust as needed)
CHUNK_SIZE = 1024  # Chunk size for sending data
UDP_IP = "127.0.0.1"  # Server IP
UDP_PORT = 9999  # Port to send UDP audio
TCP_PORT = 8888  # Port for TCP handshake
EOT_SEQ_NUM = 99999999  # End-of-transmission signal
HELLO_PACKET = b"HELLO"
WELCOME_PACKET = b"WELCOME"
TIMEOUT = 2  # Timeout for TCP in seconds
MAX_RETRIES = 3  # Maximum retries for TCP handshake

# Create UDP socket for audio
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

is_recording = True


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


def send_eot():
    """Sends an end-of-transmission (EOT) packet."""
    eot_packet = struct.pack("!I", EOT_SEQ_NUM)  # Send special sequence number
    udp_sock.sendto(eot_packet, (UDP_IP, UDP_PORT))
    print("Sent End-of-Transmission (EOT) packet.")


def wait_for_exit():
    """Waits for Enter key press to stop recording and send EOT."""
    input()  # Wait for Enter key
    print("\nStopping and sending End-of-Transmission (EOT)...")
    send_eot()
    sys.exit(0)


def main():
    """Main entry point for the audio client."""
    # Perform TCP handshake before starting audio
    if tcp_handshake(UDP_IP, TCP_PORT):
        # Start audio recording and sending in a separate thread
        import threading
        audio_thread = threading.Thread(target=record_and_send_audio)
        audio_thread.start()

        # Wait for Enter key to stop and send EOT
        wait_for_exit()
    else:
        print("Failed to establish connection. Exiting.")
        sys.exit(1)


if __name__ == "__main__":
    main()
