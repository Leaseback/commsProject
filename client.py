"""
This Python script implements a VoIP (Voice over IP) client that records, transmits, receives,
and plays back audio data in real-time over a network. It uses a combination of UDP for audio
data transmission and TCP for initial connection and handshakes with a server.

Key features:
- The client connects to a server via a TCP handshake to establish a communication channel.
- Audio is recorded from the system's microphone, packed into packets, and sent over UDP to
  a target client/server.
- A jitter buffer is used to handle network-induced delays and packet reordering, ensuring
  smooth playback.
- Audio is played back in real-time on the receiving side, with synchronization and jitter
  handling for seamless audio experience.
- The client periodically sends heartbeat messages to the server to ensure the connection is
  still active.
- The client supports sending an "End of Transmission" (EOT) signal to indicate that the
  audio transmission has ended.
- The client is designed to be robust, handling network timeouts, retries, and errors in
  packet reception and transmission.
"""

# imports
import sounddevice as sd  # Library for audio input and output handling
import numpy as np  # Library for numerical operations, used to handle audio data
import socket  # Provides access to socket interfaces for networking
import struct  # For packing and unpacking binary data into specific formats
import sys  # Provides access to system-specific parameters
import threading  # For creating concurrent threads
import time  # For handling time-based events
import argparse  # For parsing command-line arguments
from collections import deque  # For using a deque, ideal for jitter buffer

# constants
SAMPLE_RATE = 44100  # Audio sample rate in Hz
CHANNELS = 1  # Mono audio
CHUNK_SIZE = 882  # Each audio chunk has 882 samples
BYTES_PER_PACKET = CHUNK_SIZE * 2  # 16-bit (2 bytes per sample), mono (1 channel) audio
PACKET_SIZE = 2200  # Size of each UDP packet, slightly larger than the audio packet size for headers
EOT_SEQ_NUM = 99999999  # Special sequence number to indicate EOT packet
JITTER_BUFFER_SIZE = 8  # The size of the jitter buffer (how many packets to store before playing)
PLAYBACK_INTERVAL_MS = 10  # Time (in ms) between audio playback iterations
TCP_PORT = 8888  # TCP port for the handshake with the server
UDP_SERVER_PORT = 9999  # UDP port to receive and send audio data
TIMEOUT = 2  # Timeout in seconds for waiting on network operations
MAX_RETRIES = 3  # Maximum retries for the TCP handshake with the server
HEARTBEAT_INTERVAL = 30  # Interval (in seconds) for sending heartbeat packets to check server availability
SILENCE_THRESHOLD = 0.01  # Amplitude threshold to warn if the audio input is too quiet (for debug)

"""
JitterBuffer class is used to reorder out-of-sequence packets to ensure smooth playback
"""
class JitterBuffer:

    """
    initialization function
    """
    def __init__(self, max_size):
        # Initialize jitter buffer with maximum capacity
        self.buffer = deque(maxlen=max_size)  # A deque automatically discards old items once the max size is exceeded
        self.max_size = max_size  # Max buffer size
        self.expected_seq_num = None  # Initially no expected sequence number

    """
    Adds a new packet to the jitter buffer after verifying its sequence number
    """
    def add_packet(self, seq_num, audio_data):
        # If the packet's sequence number is too old, discard it
        if self.expected_seq_num is not None and seq_num < self.expected_seq_num - self.max_size:
            return False
        packet = (seq_num, audio_data)  # Create a tuple of sequence number and audio data
        if not self.buffer:  # If the buffer is empty, simply add the first packet
            self.buffer.append(packet)
            self.expected_seq_num = seq_num  # Set the expected sequence number for the next packet
            return True
        # Check for duplicates: avoid adding packets that have already been received
        for existing_seq, _ in self.buffer:
            if seq_num == existing_seq:
                return False
        temp = list(self.buffer)  # Convert buffer to a list for sorting
        temp.append(packet)  # Add the new packet to the list
        temp.sort(key=lambda x: x[0])  # Sort the packets by their sequence number
        self.buffer.clear()  # Clear the current buffer
        for item in temp[-self.max_size:]:  # Refill the buffer with sorted packets, limited by max_size
            self.buffer.append(item)
        return True

    """
    Retrieves the next packet from the buffer, ordered by sequence number
    """
    def get_packet(self):
        if not self.buffer:  # Return None if the buffer is empty
            return None, None
        seq_num, audio_data = self.buffer.popleft()  # Pop the first packet
        self.expected_seq_num = seq_num + 1  # Update the expected sequence number for the next packet
        return seq_num, audio_data  # Return the sequence number and audio data of the next packet

"""
The Client class handles everything from TCP handshakes to recording and playback
"""
class Client:

    """
    initialization function
    """
    def __init__(self, udp_port, server_ip, target_ip):
        # Initialize the client with essential properties
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP socket for audio data transmission
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow reuse of local addresses
        self.udp_sock.bind(("0.0.0.0", udp_port))  # Bind the UDP socket to the specified port
        self.udp_sock.settimeout(1.0)  # Set socket timeout to 1 second for network operations
        self.server_ip = server_ip  # IP address of the server
        self.target_ip = target_ip  # IP address of the target client
        self.udp_port = udp_port  # Port number for sending/receiving audio
        self.jitter_buffer = JitterBuffer(JITTER_BUFFER_SIZE)  # Initialize jitter buffer to handle packet reordering
        self.is_running = True  # Flag to control whether the client is running or not
        self.is_recording = True  # Flag to indicate if the client is still recording
        self.eot_received = False  # Flag to indicate if End of Transmission (EOT) signal has been received
        self.sequence_number = 0  # Initial sequence number for the audio packets

    """
    Performs the TCP handshake with the server to initiate communication
    """
    def tcp_handshake(self):
        hello_packet = b"HELLO" + struct.pack(">I", self.udp_port) + self.target_ip.encode()  # Create a hello packet with UDP port and target IP
        for attempt in range(MAX_RETRIES):  # Retry up to MAX_RETRIES times if the handshake fails
            try:
                print(f"Attempting TCP handshake with {self.server_ip}:{TCP_PORT} (Attempt {attempt + 1})...")
                tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Create a TCP socket
                tcp_sock.settimeout(TIMEOUT)  # Set a timeout for the connection
                tcp_sock.connect((self.server_ip, TCP_PORT))  # Connect to the server on the specified TCP port
                tcp_sock.send(hello_packet)  # Send the hello packet
                response = tcp_sock.recv(1024)  # Wait for a response from the server
                if response == b"WELCOME":  # Server accepted the handshake
                    print("Handshake successful!")
                    return True
                elif response == b"FULL":  # Server is full, reject the connection
                    print("Server is full.")
                    return False
                else:  # Unexpected response from server
                    print("Unexpected response during handshake.")
            except (socket.timeout, ConnectionRefusedError) as e:  # Catch connection errors and timeouts
                print(f"Handshake failed: {e}")
            finally:
                try:
                    tcp_sock.close()  # Close the TCP socket after each attempt
                except:
                    pass
        print("Handshake failed after maximum retries.")  # Max retries exceeded
        return False

    """
    Sends periodic heartbeat messages to the server to check if it's still alive
    """
    def send_heartbeat(self):
        while self.is_running:
            try:
                tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # Create a TCP socket
                tcp_sock.settimeout(TIMEOUT)  # Set a timeout for the connection
                tcp_sock.connect((self.server_ip, TCP_PORT))  # Connect to the server
                tcp_sock.send(b"HEARTBEAT")  # Send a heartbeat message
                response = tcp_sock.recv(1024)  # Wait for response from server
                if response == b"ALIVE":  # Server acknowledges the heartbeat
                    print("Heartbeat acknowledged.")
                else:
                    print("Unexpected heartbeat response.")
            except (socket.timeout, ConnectionRefusedError):  # Handle connection errors
                print("Heartbeat failed. Server may be offline.")
                self.is_recording = False  # Stop recording if the server is unreachable
                self.is_running = False  # Stop the client
                return
            finally:
                try:
                    tcp_sock.close()  # Close the socket after sending the heartbeat
                except:
                    pass
            time.sleep(HEARTBEAT_INTERVAL)  # Wait before sending the next heartbeat

    """
    Records audio and sends it to the server as packets
    """
    def record_and_send_audio(self):
        print("Starting audio recording...")
        def callback(indata, frames, time, status):
            if status:
                print(f"Input status: {status}")  # Display input status if there's an issue with audio input
            if not self.is_recording:  # If recording is stopped, exit the callback
                return
            # Convert float audio data into 16-bit integer format and then to bytes
            audio_data = (indata * 32767).astype(np.int16)
            audio_bytes = audio_data.tobytes()  # Convert the numpy array to raw bytes
            for i in range(0, len(audio_bytes), BYTES_PER_PACKET):  # Split audio data into packets
                chunk = audio_bytes[i:i + BYTES_PER_PACKET]  # Get a chunk of the audio data
                if len(chunk) == BYTES_PER_PACKET:  # Only send full-sized packets
                    packet = struct.pack(">I", self.sequence_number) + chunk  # Pack the sequence number and audio chunk
                    try:
                        self.udp_sock.sendto(packet, (self.server_ip, UDP_SERVER_PORT))  # Send the packet via UDP
                        self.sequence_number += 1  # Increment the sequence number for the next packet
                    except Exception as e:
                        print(f"Error sending packet: {e}")  # Handle any errors that occur during sending
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=CHUNK_SIZE, callback=callback):
                print("Input stream opened.")  # Indicate that the audio input stream is opened
                while self.is_recording:
                    sd.sleep(20)  # Sleep briefly between chunks of audio data to avoid high CPU usage
        except Exception as e:
            print(f"InputStream error: {e}")  # Handle any errors that occur while setting up the input stream
            self.is_recording = False  # Stop recording if an error occurs

    """
    Plays back received audio from the jitter buffer
    """
    def play_audio(self):
        print("Starting audio playback...")
        with sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=np.float32) as stream:
            while self.is_running and not self.eot_received:  # Keep playing audio until the client stops or EOT is received
                seq_num, audio_bytes = self.jitter_buffer.get_packet()  # Retrieve the next packet from the jitter buffer
                if audio_bytes is None:  # If the buffer is empty, play silence
                    silence = np.zeros((CHUNK_SIZE, CHANNELS), dtype=np.float32)
                    stream.write(silence)
                    print("Playing silence")
                else:
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0  # Normalize the audio
                    audio_data = np.reshape(audio_data, (-1, CHANNELS))  # Reshape to the correct format
                    if audio_data.shape[0] < CHUNK_SIZE:  # If the data has fewer samples than expected, pad with silence
                        audio_data = np.pad(audio_data, ((0, CHUNK_SIZE - audio_data.shape[0]), (0, 0)))
                    elif audio_data.shape[0] > CHUNK_SIZE:  # If the data has more samples, trim it
                        audio_data = audio_data[:CHUNK_SIZE]
                    stream.write(audio_data)  # Play the audio
                    print(f"Playing packet seq_num: {seq_num}")
                time.sleep(PLAYBACK_INTERVAL_MS / 1000.0)  # Wait before playing the next packet

    """
    Receives audio packets from the server and adds them to the jitter buffer
    """
    def receive_audio(self):
        print("Listening for audio packets...")
        while self.is_running:
            try:
                packet, addr = self.udp_sock.recvfrom(PACKET_SIZE)  # Receive a packet from the server
                if len(packet) < 4:  # If the packet is too small to contain valid data, skip it
                    continue
                seq_num = struct.unpack(">I", packet[:4])[0]  # Extract the sequence number from the packet
                audio_data = packet[4:]  # Extract the audio data from the packet
                if seq_num == EOT_SEQ_NUM:  # If the sequence number indicates EOT, stop receiving packets
                    self.eot_received = True
                    break
                if len(audio_data) == BYTES_PER_PACKET:  # Ensure the packet contains the expected amount of audio data
                    self.jitter_buffer.add_packet(seq_num, audio_data)  # Add the packet to the jitter buffer
            except socket.timeout:  # If a timeout occurs while waiting for a packet, continue the loop
                continue
            except Exception as e:
                print(f"Error receiving packet: {e}")  # Handle any other errors during packet reception

    """
    Sends an End of Transmission (EOT) signal to the server to indicate that playback is complete
    """
    def send_eot(self):
        eot_packet = struct.pack(">I", EOT_SEQ_NUM) + b"\x00" * BYTES_PER_PACKET  # Create an EOT packet
        try:
            self.udp_sock.sendto(eot_packet, (self.server_ip, UDP_SERVER_PORT))  # Send the EOT packet to the server
        except Exception as e:
            print(f"Error sending EOT: {e}")  # Handle any errors during EOT transmission

    """
    Starts the client's main functionality: handshake, recording, receiving, playback
    """
    def start(self):
        if not self.tcp_handshake():  # Perform the TCP handshake with the server
            return  # Exit if handshake fails
        threads = [
            threading.Thread(target=self.record_and_send_audio, daemon=True),  # Thread to record and send audio
            threading.Thread(target=self.receive_audio, daemon=True),  # Thread to receive audio data
        ]
        for t in threads:
            t.start()  # Start the threads for recording and receiving

        time.sleep(0.2)  # Allow jitter buffer to prefill before starting playback

        playback_thread = threading.Thread(target=self.play_audio, daemon=True)  # Thread for playback
        heartbeat_thread = threading.Thread(target=self.send_heartbeat, daemon=True)  # Thread for sending heartbeat
        playback_thread.start()
        heartbeat_thread.start()

        try:
            while self.is_running:
                if input().strip().lower() == "quit":  # Listen for "quit" to stop the client
                    self.is_running = False
                    self.send_eot()  # Send the EOT packet before exiting
                    break
        except KeyboardInterrupt:
            self.is_running = False  # Stop the client if interrupted (e.g., Ctrl+C)
            self.send_eot()  # Ensure EOT is sent on shutdown

        self.udp_sock.close()  # Close the UDP socket when done

"""
Main entry point for the client, parsing command-line arguments and starting the client
"""
def main():
    parser = argparse.ArgumentParser(description="VoIP Client")  # Setup argument parser
    parser.add_argument("server_ip", help="Server URL/IP Address")  # Server IP for connection
    parser.add_argument("udp_port", help="Specify an open port on system for UDP traffic")  # UDP port for audio
    parser.add_argument("target_ip", help="IP of the other machine running the client")  # Target client IP
    args = parser.parse_args()  # Parse command-line arguments

    # Extract arguments and pass them to the Client class
    server_ip = args.server_ip
    udp_port = int(args.udp_port)
    target_ip = args.target_ip
    client = Client(udp_port, server_ip, target_ip)
    client.start()  # Start the client operations

if __name__ == "__main__":
    main()  # Execute the main function when the script is run