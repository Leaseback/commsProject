import socket
import struct
import numpy as np
import sounddevice as sd
import time
import threading
from ping3 import ping, verbose_ping
import sys

# Constants
PACKET_SIZE = 2200
EOT_SEQ_NUM = 99999999  # End-of-transmission signal
SAMPLE_RATE = 44100  # Audio sample rate
CHANNELS = 1  # Mono audio
BUFFER_SIZE = 100  # Jitter buffer size (in number of packets)
RTT_UPDATE_INTERVAL = 10  # Time in seconds to recalculate RTT
PLAYBACK_INTERVAL_MS = 20  # Play audio every XX ms
SERVER_IP = 0

class Receiver:
    def __init__(self, receiver_socket, server_ip):
        self.sock = receiver_socket
        self.server_ip = server_ip  # IP of the server to ping
        self.received_data = []  # List to store received audio chunks
        self.jitter_buffer = []  # Jitter buffer for audio packets
        self.eot_received = False
        self.rtt = 0  # Round-trip time (in milliseconds)

    def calculate_rtt(self):
        """Calculate the RTT to the server using ICMP ping."""
        try:
            ping_time = ping(self.server_ip)  # This sends an ICMP ping
            if ping_time is not None:
                self.rtt = ping_time * 1000  # RTT in milliseconds
                self.rtt = 200
                print(f"RTT calculated: {self.rtt} ms")
            else:
                print("RTT calculation failed (no response).")
        except Exception as e:
            print(f"Error calculating RTT: {e}")

    def add_to_jitter_buffer(self, packet):
        """Add a packet to the jitter buffer."""
        self.jitter_buffer.append(packet)

    def play_audio(self):
        """Play audio from the jitter buffer."""
        if len(self.jitter_buffer) > 0:
            # Concatenate all received audio chunks
            audio_bytes = b"".join(self.jitter_buffer)

            # Convert bytes back to NumPy array (16-bit PCM format)
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16) / 32767.0

            # Play the audio
            print("Receiver: Playing received audio...")
            sd.play(audio_data, samplerate=SAMPLE_RATE)
            sd.wait()
            self.jitter_buffer.clear()  # Clear the jitter buffer after playback
            print("Receiver: Playback complete.")

    def play_audio_in_thread(self):
        """Continuously play audio from jitter buffer with regular intervals."""
        print("Audio player thread started")

        # Configure non-blocking audio output
        with sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=np.float32) as stream:
            while not self.eot_received:
                if len(self.jitter_buffer) > 0:
                    # Get audio bytes from jitter buffer
                    audio_bytes = b"".join(self.jitter_buffer)
                    self.jitter_buffer.clear()

                    # Convert bytes to NumPy array (16-bit PCM format)
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0


                    # Ensure correct shape for mono audio
                    audio_data = np.reshape(audio_data, (-1, 1))

                    # Write audio data to the stream (non-blocking)
                    stream.write(audio_data)

                # Sleep for the playback interval to prevent CPU overuse
                time.sleep(PLAYBACK_INTERVAL_MS / 1000.0)  # 20ms interval

    def start(self):
        """Start receiving packets and playing audio."""
        print("Receiver: Listening for audio packets...")

        # Start playback in a separate thread
        playback_thread = threading.Thread(target=self.play_audio_in_thread)
        playback_thread.daemon = True
        playback_thread.start()

        while not self.eot_received:
            try:
                packet, addr = self.sock.recvfrom(PACKET_SIZE)

                # Handle EOT or ACK packet
                if len(packet) == 4:  # Possible EOT or ACK
                    seq_num = struct.unpack("!I", packet)[0]
                    if seq_num == EOT_SEQ_NUM:
                        print("Receiver: End of transmission received.")
                        self.eot_received = True
                        break
                if addr[0] != SERVER_IP:
                    # Add valid packet data to jitter buffer
                    self.add_to_jitter_buffer(packet)

            except socket.timeout:
                continue

    def stop(self):
        """Stop the receiver."""
        self.eot_received = True
        self.sock.close()

def main():
    if len(sys.argv) < 2:
        print("Usage: python Receiver.py <server_ip>")
        sys.exit(1)

    SERVER_IP = sys.argv[1]  # Get the server IP from command line argument

    # Initialize the receiver socket and bind to listen for packets
    receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver_sock.bind(("0.0.0.0", 9999))  # Listen on this port

    receiver = Receiver(receiver_sock, SERVER_IP)

    # Start the receiver to begin receiving packets
    receiver.start()


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
