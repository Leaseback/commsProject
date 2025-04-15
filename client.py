import sounddevice as sd
import numpy as np
import socket
import struct
import sys
import threading
import time
from collections import deque

# Constants
SAMPLE_RATE = 44100
CHANNELS = 1
CHUNK_SIZE = 882  # 20ms at 44100Hz
BYTES_PER_PACKET = CHUNK_SIZE * 2  # 1764 bytes
PACKET_SIZE = 2200  # Buffer size (1768 bytes used)
EOT_SEQ_NUM = 99999999
JITTER_BUFFER_SIZE = 4
PLAYBACK_INTERVAL_MS = 20
TCP_PORT = 8888
UDP_SERVER_PORT = 9999
TIMEOUT = 2
MAX_RETRIES = 3
HEARTBEAT_INTERVAL = 30
SILENCE_THRESHOLD = 0.01  # For debug

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

class Client:
    def __init__(self, udp_port, server_ip, target_ip):
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.bind(("0.0.0.0", udp_port))
        self.udp_sock.settimeout(1.0)
        self.server_ip = server_ip
        self.target_ip = target_ip
        self.udp_port = udp_port
        self.jitter_buffer = JitterBuffer(JITTER_BUFFER_SIZE)
        self.is_running = True
        self.is_recording = True
        self.eot_received = False
        self.sequence_number = 0

    def tcp_handshake(self):
        hello_packet = b"HELLO" + struct.pack(">I", self.udp_port) + self.target_ip.encode()
        for attempt in range(MAX_RETRIES):
            try:
                print(f"Attempting TCP handshake with {self.server_ip}:{TCP_PORT} (Attempt {attempt + 1})...")
                tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp_sock.settimeout(TIMEOUT)
                tcp_sock.connect((self.server_ip, TCP_PORT))
                tcp_sock.send(hello_packet)
                response = tcp_sock.recv(1024)
                if response == b"WELCOME":
                    print("Handshake successful!")
                    return True
                elif response == b"FULL":
                    print("Server is full.")
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

    def send_heartbeat(self):
        while self.is_running:
            try:
                tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp_sock.settimeout(TIMEOUT)
                tcp_sock.connect((self.server_ip, TCP_PORT))
                tcp_sock.send(b"HEARTBEAT")
                response = tcp_sock.recv(1024)
                if response == b"ALIVE":
                    print("Heartbeat acknowledged.")
                else:
                    print("Unexpected heartbeat response.")
            except (socket.timeout, ConnectionRefusedError):
                print("Heartbeat failed. Server may be offline.")
                self.is_recording = False
                self.is_running = False
                return
            finally:
                try:
                    tcp_sock.close()
                except:
                    pass
            time.sleep(HEARTBEAT_INTERVAL)

    def record_and_send_audio(self):
        print("Starting audio recording...")
        def callback(indata, frames, time, status):
            if status:
                print(f"Input status: {status}")
            if not self.is_recording:
                return
            peak_amplitude = np.max(np.abs(indata))
            print(f"Recording chunk, peak amplitude: {peak_amplitude:.4f}")
            if peak_amplitude < SILENCE_THRESHOLD:
                print("Warning: Audio input is very quiet.")
            audio_data = (indata * 32767).astype(np.int16)
            audio_bytes = audio_data.tobytes()
            for i in range(0, len(audio_bytes), BYTES_PER_PACKET):
                chunk = audio_bytes[i:i + BYTES_PER_PACKET]
                if len(chunk) == BYTES_PER_PACKET:
                    packet = struct.pack(">I", self.sequence_number) + chunk
                    try:
                        self.udp_sock.sendto(packet, (self.server_ip, UDP_SERVER_PORT))
                        print(f"Sent packet seq_num: {self.sequence_number}, size: {len(packet)}")
                        self.sequence_number += 1
                    except Exception as e:
                        print(f"Error sending packet: {e}")
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=CHUNK_SIZE, callback=callback):
                print("Input stream opened.")
                while self.is_recording:
                    sd.sleep(20)
        except Exception as e:
            print(f"InputStream error: {e}")
            self.is_recording = False

    def play_audio(self):
        print("Starting audio playback...")
        with sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype=np.float32) as stream:
            while self.is_running and not self.eot_received:
                seq_num, audio_bytes = self.jitter_buffer.get_packet()
                if audio_bytes is None:
                    silence = np.zeros((CHUNK_SIZE, CHANNELS), dtype=np.float32)
                    stream.write(silence)
                    print("Playing silence")
                else:
                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
                    audio_data = np.reshape(audio_data, (-1, CHANNELS))
                    if audio_data.shape[0] < CHUNK_SIZE:
                        audio_data = np.pad(audio_data, ((0, CHUNK_SIZE - audio_data.shape[0]), (0, 0)))
                    elif audio_data.shape[0] > CHUNK_SIZE:
                        audio_data = audio_data[:CHUNK_SIZE]
                    stream.write(audio_data)
                    print(f"Playing packet seq_num: {seq_num}")
                time.sleep(PLAYBACK_INTERVAL_MS / 1000.0)

    def receive_audio(self):
        print("Listening for audio packets...")
        while self.is_running:
            try:
                packet, addr = self.udp_sock.recvfrom(PACKET_SIZE)
                print(f"Received packet from {addr}, size: {len(packet)}")
                if len(packet) < 4:
                    print("Discarded short packet")
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

    def send_eot(self):
        eot_packet = struct.pack(">I", EOT_SEQ_NUM) + b"\x00" * BYTES_PER_PACKET
        try:
            self.udp_sock.sendto(eot_packet, (self.server_ip, UDP_SERVER_PORT))
            print(f"Sent EOT packet seq_num: {EOT_SEQ_NUM}")
        except Exception as e:
            print(f"Error sending EOT: {e}")

    def start(self):
        if not self.tcp_handshake():
            print("Failed to connect. Exiting.")
            return
        threads = [
            threading.Thread(target=self.record_and_send_audio, daemon=True),
            threading.Thread(target=self.receive_audio, daemon=True),
            threading.Thread(target=self.play_audio, daemon=True),
            threading.Thread(target=self.send_heartbeat, daemon=True)
        ]
        for t in threads:
            t.start()
        print("Client running. Type 'quit' to stop.")
        try:
            while self.is_running:
                if input().strip().lower() == "quit":
                    print("Shutting down...")
                    self.is_recording = False
                    self.is_running = False
                    self.send_eot()
                    time.sleep(0.1)
                    break
        except KeyboardInterrupt:
            print("Interrupted. Shutting down...")
            self.is_recording = False
            self.is_running = False
            self.send_eot()
        self.udp_sock.close()

def main():
    if len(sys.argv) < 4:
        print("Usage: python client.py <server_ip> <udp_port> <target_ip>")
        sys.exit(1)
    server_ip = sys.argv[1]
    udp_port = int(sys.argv[2])
    target_ip = sys.argv[3]
    client = Client(udp_port, server_ip, target_ip)
    client.start()

if __name__ == "__main__":
    main()
    