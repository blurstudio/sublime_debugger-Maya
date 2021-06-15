
from Debugger.modules.typecheck import *
import Debugger.modules.debugger.adapter as adapter

from posixpath import basename
from shutil import which
import socket

from os.path import dirname, split, join
from .util import debugpy_path, ATTACH_TEMPLATE, RUN_TEMPLATE, EXEC_COMMAND, log as custom_log
from tempfile import gettempdir

import threading
import sublime


# This is the id of your adapter. It must be unique and match no 
# other existing adapters.
adapter_type = "mayapy"


class Maya(adapter.AdapterConfiguration):

	@property
	def type(self): return adapter_type

	async def start(self, log, configuration):
		"""
		start() is called when the play button is pressed in the debugger.
		
		The configuration is passed in, allowing you to get necessary settings
		to use when setting up the adapter as it starts up (such as getting the 
		desired host/port to connect to, show below)

		The configuration will be chosen by the user from the 
		configuration_snippets function below, and its contents are the contents 
		of "body:". However, the user can change the configurations manually so 
		make sure to account for unexpected changes. 
		"""

		# Start by finding the python installation on the system
		python = configuration.get("pythonPath")

		if not python:
			if which("python3"):
				python = "python3"
			elif not (python := which("python")):
				raise Exception('No python installation found')
		
		custom_log(f"Found python install: {python}")

		# --- Send attach code to maya first ---
		maya_host, maya_port = configuration['maya']['host'], int(configuration['maya']['port'])
		client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

		try:
			client.settimeout(3)
			client.connect((maya_host, maya_port))
		except:
			# Raise an error to show a potential solution to this problem.
			raise Exception(
				"""
				
				
				
					Please run the following command in Maya and try again:
					cmds.commandPort(name="{host}:{port}", sourceType="mel")
				""".format(host=maya_host, port=maya_port)
			)
		
		# Get debugpy host/port from config
		host = configuration['debugpy']['host']
		if host == 'localhost':
			host = '127.0.0.1'
		port = int(configuration['debugpy']['port'])

		# Create helper function
		def send_to_maya(code):
			# Create a temporary file, keeping its path, and
			# populate it with the given code to run
			filepath = join(gettempdir(), 'temp.py')
			with open(filepath, "w") as file:
				file.write(code)

			# Format the mel command to execute the temporary file
			cmd = EXEC_COMMAND.format(
				tmp_file_path=filepath.replace('\\', '\\\\\\\\')
			)

			# Send the code to maya
			client.send(cmd.encode('UTF-8'))
		
		# Format ATTACH_TEMPLATE to set up debugpy in the background
		attach_code = ATTACH_TEMPLATE.format(
			debugpy_path=debugpy_path,
			hostname=host,
			port=port,
			interpreter=python,
		)
		
		send_to_maya(attach_code)

		# Format RUN_TEMPLATE to point to the file containing the code to run
		run_code = RUN_TEMPLATE.format(
			dir=dirname(configuration['program']),
			file_name=split(configuration['program'])[1][:-3] or basename(split(configuration['program'])[0])[:-3]
		)

		# Set up timer to send the run code 1 sec after establishing the connection with debugpy
		threading.Timer(1, send_to_maya, args=(run_code,))
		
		# Start the transport
		return adapter.SocketTransport(log, host, port)

	async def install(self, log):
		"""
		When someone installs your adapter, they will also have to install it 
		through the debugger itself. That is when this function is called. It
		allows you to download any extra files or resources, or install items
		to other parts of the device to prepare for debugging in the future
		"""
		
		# Nothing to do when installing, just return
		pass

	@property
	def installed_version(self) -> Optional[str]:
		# The version is only used for display in the UI
		return '0.0.1'

	@property
	def configuration_snippets(self) -> Optional[list]:
		"""
		You can have several configurations here depending on your adapter's 
		offered functionalities, but they all need a "label", "description", 
		and "body"
		"""

		return [
			{
				"label": "Maya: Python Debugging",
				"description": "Run and Debug Python code in Maya",
				"body": {
					"name": "Maya: Python Debugging",  
					"type": adapter_type,
					"program": "\${file\}",
					"request": "attach",  # can only be attach or launch
					"maya":  # The host/port over which maya commands will be sent
					{
						"host": "localhost",
						"port": 7001
					},
					"debugpy":  # The host/port used to communicate with debugpy in maya
					{
						"host": "localhost",
						"port": 7002
					},
				}
			},
		]

	@property
	def configuration_schema(self) -> Optional[dict]:
		"""
		I am not completely sure what this function is used for. However, 
		it must be present.
		"""

		return None

	async def configuration_resolve(self, configuration):
		"""
		In this function, you can take a currently existing configuration and 
		resolve various variables in it before it gets passed to start().

		Therefore, configurations where values are stated as {my_var} can 
		then be filled out before being used to start the adapter.
		"""

		return configuration
