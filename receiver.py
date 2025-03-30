import socket
import struct
import numpy as np
import sounddevice as sd
import time

# Constants
PACKET_SIZE = 1024
EOT_SEQ_NUM = 99999999  # End-of-transmission signal
SAMPLE_RATE = 44100  # Audio sample rate
CHANNELS = 1  # Mono audio


class Receiver:
    def __init__(self, receiver_socket):
        self.sock = receiver_socket
        self.received_data = []  # List to store received audio chunks
        self.eot_received = False

    def start(self):
        """Start receiving packets and play the audio after EOT."""
        print("Receiver: Listening for audio packets...")
        while not self.eot_received:
            packet, _ = self.sock.recvfrom(PACKET_SIZE)

            # Handle end-of-transmission packet
            if len(packet) == 4:  # Possible EOT or ACK
                seq_num = struct.unpack("!I", packet)[0]
                if seq_num == EOT_SEQ_NUM:
                    print("Receiver: End of transmission received. Playing audio...")
                    self.play_audio()
                    self.eot_received = True
                    break

            # Add valid packet data to list
            self.received_data.append(packet)

    def play_audio(self):
        """Plays the received audio immediately."""
        if not self.received_data:
            print("Receiver: No audio data received.")
            return

        # Concatenate all received audio chunks
        audio_bytes = b"".join(self.received_data)

        # Convert bytes back to NumPy array (16-bit PCM format)
        audio_data = np.frombuffer(audio_bytes, dtype=np.int16) / 32767.0

        # Play the audio
        print("Receiver: Playing received audio...")
        sd.play(audio_data, samplerate=SAMPLE_RATE)
        sd.wait()
        print("Receiver: Playback complete.")




def main():
    # Initialize the receiver socket and bind to listen for packets
    receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver_sock.bind(("localhost", 9999))  # Listen on this port

    receiver = Receiver(receiver_sock)

    # Start the receiver to begin receiving packets
    receiver.start()


if __name__ == "__main__":
    main()
