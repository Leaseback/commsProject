"""
this program will automatically install all the dependencies listed in the requirements.txt file
"""

#imports
import subprocess

#installs requirements
subprocess.check_call(["pip", "install", "-r", "requirements.txt"])