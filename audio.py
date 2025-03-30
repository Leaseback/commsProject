import sounddevice as sd
import numpy as np
import socket
import struct
import threading
import sys

# Constants
SAMPLE_RATE = 44100  # Samples per second
CHANNELS = 1  # Mono audio
THRESHOLD = 0.05  # Silence threshold (adjust as needed)
CHUNK_SIZE = 1024  # Chunk size for sending data
UDP_IP = "127.0.0.1"  # Localhost
UDP_PORT = 9999  # Port to send data
EOT_SEQ_NUM = 99999999  # End-of-transmission signal

# Create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

is_recording = True


def record_and_send_audio():
    """Continuously records audio and sends packets over UDP if voice is detected."""
    print("Recording and sending... Press Enter to stop and send EOT.")

    def callback(indata, frames, time, status):
        """Callback to process incoming audio data."""
        if status:
            print(status)

        # Measure volume (RMS of audio data)
        volume_norm = np.linalg.norm(indata) / np.sqrt(len(indata))

        # Only send audio if volume exceeds the threshold (voice detected)
        if volume_norm > THRESHOLD:
            # Convert audio to 16-bit PCM and bytes
            audio_bytes = (indata * 32767).astype(np.int16).tobytes()

            # Send in CHUNK_SIZE packets
            for i in range(0, len(audio_bytes), CHUNK_SIZE):
                chunk = audio_bytes[i:i + CHUNK_SIZE]
                sock.sendto(chunk, (UDP_IP, UDP_PORT))

    # Open the input stream and record continuously
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=callback):
        while is_recording:
            sd.sleep(100)


def wait_for_exit():
    """Waits for Enter key press to stop recording and send EOT."""
    input()  # Wait for Enter key
    print("\nStopping and sending End-of-Transmission (EOT)...")
    send_eot()
    sys.exit(0)


def send_eot():
    """Sends an end-of-transmission packet."""
    eot_packet = struct.pack("!I", EOT_SEQ_NUM)  # Send special sequence number
    sock.sendto(eot_packet, (UDP_IP, UDP_PORT))
    print("Sent End-of-Transmission (EOT) packet.")


if __name__ == "__main__":
    # Start audio recording in a separate thread
    audio_thread = threading.Thread(target=record_and_send_audio)
    audio_thread.start()

    # Wait for Enter key to send EOT and stop
    wait_for_exit()
