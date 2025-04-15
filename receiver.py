import socket
import struct
import numpy as np
import sounddevice as sd
import time
import threading
from ping3 import ping
import sys
from collections import deque

# Constants
PACKET_SIZE = 2200
EOT_SEQ_NUM = 99999999
SAMPLE_RATE = 44100
CHANNELS = 1
JITTER_BUFFER_SIZE = 4
RTT_UPDATE_INTERVAL = 10
PLAYBACK_INTERVAL_MS = 20
SAMPLES_PER_PACKET = 882
SERVER_IP = None
TCP_PORT = 8888
UDP_PORT = 10000  # Receiver's UDP port
HELLO_PACKET = b"HELLO" + struct.pack(">I", UDP_PORT)  # Send port
WELCOME_PACKET = b"WELCOME"
TIMEOUT = 2
MAX_RETRIES = 3

class JitterBuffer:
    def __init__(self, max_size):
        self.buffer = deque(maxlen=max_size)
        self.max_size = max_size
        self.expected_seq_num = None

    def add_packet(self, seq_num, audio_data):
        if self.expected_seq_num is not None and seq_num < self.expected_seq_num - self.max_size:
            return False
        packet = (seq_num, audio_data)
        if not self.buffer:
            self.buffer.append(packet)
            self.expected_seq_num = seq_num
            return True
        for existing_seq, _ in self.buffer:
            if seq_num == existing_seq:
                return False
        temp = list(self.buffer)
        temp.append(packet)
        temp.sort(key=lambda x: x[0])
        self.buffer.clear()
        for item in temp[-self.max_size:]:
            self.buffer.append(item)
        return True

    def get_packet(self):
        if not self.buffer:
            return None, None
        seq_num, audio_data = self.buffer[0]
        if self.expected_seq_num is None or seq_num <= self.expected_seq_num:
            self.buffer.popleft()
            self.expected_seq_num = seq_num + 1
            return seq_num, audio_data
        return None, None

    def size(self):
        return len(self.buffer)

class Receiver:
    def __init__(self, receiver_socket, server_ip):
        self.sock = receiver_socket
        self.server_ip = server_ip
        self.jitter_buffer = JitterBuffer(JITTER_BUFFER_SIZE)
        self.eot_received = False
        self.rtt = 100
        self.running = True
        self.last_rtt_update = 0

    def calculate_rtt(self):
        try:
            ping_time = ping(self.server_ip)
            if ping_time is not None:
                self.rtt = ping_time * 1000
                print(f"RTT: {self.rtt:.2f} ms")
            else:
                print("RTT failed. Using previous RTT.")
        except Exception as e:
            print(f"Error calculating RTT: {e}")

    def play_audio_in_thread(self):
        print("Audio player thread started")
        with sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=np.float32) as stream:
            while self.running and not self.eot_received:
                if time.time() - self.last_rtt_update > RTT_UPDATE_INTERVAL:
                    self.calculate_rtt()
                    self.last_rtt_update = time.time()
                seq_num, audio_bytes = self.jitter_buffer.get_packet()
                if audio_bytes is None:
                    silence = np.zeros((SAMPLES_PER_PACKET, CHANNELS), dtype=np.float32)
                    stream.write(silence)
                else:
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                    audio_data = np.reshape(audio_data, (-1, CHANNELS))
                    if audio_data.shape[0] < SAMPLES_PER_PACKET:
                        audio_data = np.pad(audio_data, ((0, SAMPLES_PER_PACKET - audio_data.shape[0]), (0, 0)))
                    elif audio_data.shape[0] > SAMPLES_PER_PACKET:
                        audio_data = audio_data[:SAMPLES_PER_PACKET]
                    stream.write(audio_data)
                time.sleep(PLAYBACK_INTERVAL_MS / 1000.0)

    def start(self):
        print("Receiver: Listening for audio packets...")
        self.sock.settimeout(1.0)
        playback_thread = threading.Thread(target=self.play_audio_in_thread)
        playback_thread.daemon = True
        playback_thread.start()
        while self.running:
            try:
                packet, addr = self.sock.recvfrom(PACKET_SIZE)
                print(f"Received packet from {addr}, size: {len(packet)}")
                if addr[0] != self.server_ip or len(packet) < 4:
                    print(f"Discarded packet from {addr}")
                    continue
                seq_num = struct.unpack(">I", packet[:4])[0]
                audio_data = packet[4:]
                if seq_num == EOT_SEQ_NUM:
                    print("Received EOT signal")
                    self.eot_received = True
                    break
                if len(audio_data) == BYTES_PER_PACKET:
                    self.jitter_buffer.add_packet(seq_num, audio_data)
                    print(f"Added packet seq_num: {seq_num}")
                else:
                    print(f"Invalid audio data size: {len(audio_data)}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving packet: {e}")

    def stop(self):
        self.running = False
        self.sock.close()

def tcp_handshake(server_ip, tcp_port):
    for attempt in range(MAX_RETRIES):
        try:
            print(f"Attempting TCP handshake with {server_ip}:{tcp_port} (Attempt {attempt + 1})...")
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.settimeout(TIMEOUT)
            tcp_sock.connect((server_ip, tcp_port))
            tcp_sock.send(HELLO_PACKET)
            response = tcp_sock.recv(1024)
            if response == WELCOME_PACKET:
                print("Handshake successful! Ready to receive audio.")
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

def main():
    if len(sys.argv) < 2:
        print("Usage: python receiver.py <server_ip>")
        sys.exit(1)
    global SERVER_IP, BYTES_PER_PACKET
    SERVER_IP = sys.argv[1]
    BYTES_PER_PACKET = SAMPLES_PER_PACKET * 2
    if not tcp_handshake(SERVER_IP, TCP_PORT):
        print("Failed to establish connection. Exiting.")
        sys.exit(1)
    receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver_sock.bind(("0.0.0.0", UDP_PORT))
    receiver = Receiver(receiver_sock, SERVER_IP)
    try:
        receiver.start()
    except KeyboardInterrupt:
        print("Shutting down receiver...")
        receiver.stop()

if __name__ == "__main__":
    main()