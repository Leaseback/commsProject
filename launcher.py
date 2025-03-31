import subprocess
import sys
import time


def launch_sender(server_ip):
    """Launch the Audio sender script."""
    return subprocess.Popen([sys.executable, 'audio.py', server_ip])


def launch_receiver(server_ip):
    """Launch the Audio receiver script."""
    return subprocess.Popen([sys.executable, 'receiver.py', server_ip])


def main():
    # Get the server IP from the user
    server_ip = input("Enter the server IP address: ")

    # Launch the sender and receiver scripts in separate processes
    print("Launching sender and receiver...")
    sender_process = launch_sender(server_ip)
    receiver_process = launch_receiver(server_ip)

    # Keep the launcher script running until the user exits
    try:
        while True:
            time.sleep(1)  # Keep the main thread alive
    except KeyboardInterrupt:
        print("Terminating processes...")
        sender_process.terminate()  # Terminate sender process
        receiver_process.terminate()  # Terminate receiver process
        sender_process.wait()  # Wait for sender to finish
        receiver_process.wait()  # Wait for receiver to finish
        print("Processes terminated.")


if __name__ == "__main__":
    main()
