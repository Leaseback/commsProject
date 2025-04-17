This program allows you to host a server and have clients connect to it and voice chat

To begin:
1) Download the program
2) Ensure all dependencies are installed by running install_requirements.py
3) Run server.py on desired host machine for the server
4) Run client.py (usage explained below) on each client
5) Chat!

USAGE OF CLIENT

can be compiled and ran using python client.py

The client program requires 3 arguments: server_ip udp_port target_port
server_ip: ip address of the server to connect through
udp port: udp port to use for udp traffic
target_port: ip of the other machine that you wish to connect with
(you can get more information on these parameters by running python client.py -h)
example:
python client.py 127.0.0.1 5002 127.0.0.1

USAGE OF SERVER

can be compiled and ran using python server.py

The server program takes no arguments
example:
python server.py

Server:
- Can be hosted over local network or port forwarded to support users outside of local network joining.
- Ports 8888 should be open for TCP Inbound/Outbound, Ports 9999 should be open for UCP Inbound/Outbound