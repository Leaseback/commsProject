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
CHUNK_SIZE = 882
BYTES_PER_PACKET = CHUNK_SIZE * 2
UDP_IP = "127.0.0.1"
UDP_PORT = 9999
TCP_PORT = 8888
EOT_SEQ_NUM = 99999999
HELLO_PACKET = b"HELLO" + struct.pack(">I", UDP_PORT)
WELCOME_PACKET = b"WELCOME"
HEARTBEAT_PACKET = b"HEARTBEAT"
TIMEOUT = 2
MAX_RETRIES = 3
HEARTBEAT_INTERVAL = 30
SILENCE_THRESHOLD = 0.01  # For detecting silent input

udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
is_recording = True
heartbeat_active = True
sequence_number = 0

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
    global heartbeat_active, is_recording
    while heartbeat_active:
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.settimeout(TIMEOUT)
            tcp_sock.connect((server_ip, tcp_port))
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
    global sequence_number, is_recording
    print("Starting audio recording... Type 'quit' to stop and send EOT.")
    def callback(indata, frames, time, status):
        global sequence_number
        if status:
            print(f"Input status: {status}")
        if not is_recording:
            return
        # Debug: Check audio amplitude
        peak_amplitude = np.max(np.abs(indata))
        print(f"Recording chunk, peak amplitude: {peak_amplitude:.4f}")
        if peak_amplitude < SILENCE_THRESHOLD:
            print("Warning: Audio input is very quiet. Check microphone.")
        audio_data = (indata * 32767).astype(np.int16)
        audio_bytes = audio_data.tobytes()
        for i in range(0, len(audio_bytes), BYTES_PER_PACKET):
            chunk = audio_bytes[i:i + BYTES_PER_PACKET]
            if len(chunk) == BYTES_PER_PACKET:
                packet = struct.pack(">I", sequence_number) + chunk
                try:
                    udp_sock.sendto(packet, (UDP_IP, UDP_PORT))
                    print(f"Sent packet seq_num: {sequence_number}, size: {len(packet)} bytes to {UDP_IP}:{UDP_PORT}")
                    sequence_number += 1
                except Exception as e:
                    print(f"Error sending packet: {e}")
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=CHUNK_SIZE, callback=callback):
            print("Input stream opened successfully.")
            while is_recording:
                sd.sleep(20)
    except Exception as e:
        print(f"Error in InputStream: {e}")
        is_recording = False

def send_eot():
    eot_packet = struct.pack(">I", EOT_SEQ_NUM) + b"\x00" * BYTES_PER_PACKET
    try:
        udp_sock.sendto(eot_packet, (UDP_IP, UDP_PORT))
        print(f"Sent EOT packet seq_num: {EOT_SEQ_NUM}, size: {len(eot_packet)} bytes")
    except Exception as e:
        print(f"Error sending EOT packet: {e}")
    udp_sock.close()

def wait_for_exit():
    global is_recording, heartbeat_active
    while True:
        user_input = input().strip().lower()
        if user_input == "quit":
            print("\nDisconnecting from server and shutting down...")
            is_recording = False
            send_eot()
            heartbeat_active = False
            time.sleep(0.1)
            sys.exit(0)
        else:
            print("Type 'quit' to stop and send EOT.")

def main():
    global UDP_IP
    if len(sys.argv) < 2:
        print("Usage: python audio.py <server_ip>")
        sys.exit(1)
    server_ip = sys.argv[1]
    UDP_IP = server_ip
    if tcp_handshake(server_ip, TCP_PORT):
        audio_thread = threading.Thread(target=record_and_send_audio)
        audio_thread.daemon = True
        audio_thread.start()
        heartbeat_thread = threading.Thread(target=send_heartbeat, args=(server_ip, TCP_PORT))
        heartbeat_thread.daemon = True
        heartbeat_thread.start()
        wait_for_exit()
    else:
        print("Failed to establish connection. Exiting.")
        sys.exit(1)

if __name__ == "__main__":
    main()