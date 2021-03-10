
"""

This script creates a connection between the Debugger and Maya for debugging.

It is inspired by various packages, namely:
    - https://github.com/daveleroy/sublime_debugger
    - https://github.com/FXTD-ODYSSEY/vscode-mayapy
    - https://github.com/justinfx/MayaSublime

Dataflow Schematic:

                                   Sublime Text
                                        |
                        -----------> Debugger -----------
                        \                                \
                        \                                v
                debugger_send_loop()                   main() ---> on_receive_from_debugger()
                         ^                                             /          \
                         \                           -- fwd info to --          attach?
                   fwd debugpy response              /                                \
                           \                     v                                  v
                            -------  start_maya_debugging()  <--- starts ---  attach_to_maya()
                                        ^           /                               \
                                        res       req                                \
                                          \      v                                   v
                                        debugpy (in Maya)                   injects debugpy in Maya


"""

from interface import DebuggerInterface
from tempfile import gettempdir
from queue import Queue
from util import *
import socket
import json
import os


# Globals
interface = None

processed_seqs = []

maya_cmd_socket = socket.socket()
run_code = ""

debugpy_send_queue = Queue()
debugpy_socket = None


def main():
    """
    Starts the thread to send information to debugger, then remains in a loop
    reading messages from debugger.
    """
    
    global interface

    interface = DebuggerInterface(on_receive=on_receive_from_debugger)
    interface.start()


def on_receive_from_debugger(message):
    """
    Intercept the initialize and attach requests from the debugger
    while debugpy is being set up
    """

    contents = json.loads(message)

    log('Received from Debugger:', message)

    cmd = contents['command']
    
    if cmd == 'initialize':
        # Run init request once maya connection is established and send success response to the debugger
        interface.send(json.dumps(json.loads(INITIALIZE_RESPONSE)))  # load and dump to remove indents
        processed_seqs.append(contents['seq'])
        pass
    
    elif cmd == 'attach':
        # time to attach to maya
        run_in_new_thread(attach_to_maya, (contents,))

        # Change arguments to valid ones for debugpy
        config = contents['arguments']
        new_args = ATTACH_ARGS.format(
            dir=dirname(config['program']).replace('\\', '\\\\'),
            hostname=config['debugpy']['host'],
            port=int(config['debugpy']['port']),
            filepath=config['program'].replace('\\', '\\\\')
        )

        contents = contents.copy()
        contents['arguments'] = json.loads(new_args)
        message = json.dumps(contents)  # update contents to reflect new args

        log("New attach arguments loaded:", new_args)

    # Then just put the message in the maya debugging queue
    debugpy_send_queue.put(message)


def attach_to_maya(contents):
    """
    Defines commands to send to Maya, establishes a connection to its commandPort,
    then sends the code to inject debugpy
    """

    global run_code
    config = contents['arguments']

    attach_code = ATTACH_TEMPLATE.format(
        debugpy_path=debugpy_path,
        hostname=config['debugpy']['host'],
        port=int(config['debugpy']['port'])
    )

    run_code = RUN_TEMPLATE.format(
        dir=dirname(config['program']),
        file_name=split(config['program'])[1][:-3] or basename(split(config['program'])[0])[:-3]
    )

    log("RUN: \n" + run_code)

    # Connect to given host/port combo
    if not debug_no_maya:
        maya_host, maya_port = config['maya']['host'], int(config['maya']['port'])
        try:
            maya_cmd_socket.settimeout(3)
            maya_cmd_socket.connect((maya_host, maya_port))
        except:
            run_in_new_thread(os._exit, (0,), 1)
            raise Exception(
                """
                
                
                
                    Please run the following command in Maya and try again:
                    cmds.commandPort(name="{host}:{port}", sourceType="mel")
                """.format(host=maya_host, port=maya_port)
            )

        # then send attach code
        log('Sending attach code to Maya')
        send_code_to_maya(attach_code)

        # Force a response just in case
        try:
            maya_cmd_socket.recv(128)
        except:
            pass
        finally:
            log('Successfully attached to Maya')

    # Then start the maya debugging threads
    run_in_new_thread(start_debugging, ((config['debugpy']['host'], int(config['debugpy']['port'])),))


def send_code_to_maya(code):
    """
    Wraps the code string in a mel command, then sends it to Maya
    """

    filepath = join(gettempdir(), 'temp.py')
    with open(filepath, "w") as file:
        file.write(code)

    cmd = EXEC_COMMAND.format(
        tmp_file_path=filepath.replace('\\', '\\\\\\\\')
    )

    log("Sending " + cmd + " to Maya")
    maya_cmd_socket.send(cmd.encode('UTF-8'))


def start_debugging(address):
    """
    Connects to debugpy in Maya, then starts the threads needed to
    send and receive information from it
    """

    log("Connecting to " + address[0] + ":" + str(address[1]))

    global debugpy_socket
    debugpy_socket = socket.create_connection(address)

    log("Successfully connected to Maya for debugging. Starting...")

    run_in_new_thread(debugpy_send_loop)  # Start sending requests to debugpy

    fstream = debugpy_socket.makefile()

    while True:
        try:
            content_length = 0
            while True:
                header = fstream.readline()
                if header:
                    header = header.strip()
                if not header:
                    break
                if header.startswith(CONTENT_HEADER):
                    content_length = int(header[len(CONTENT_HEADER):])

            if content_length > 0:
                total_content = ""
                while content_length > 0:
                    content = fstream.read(content_length)
                    content_length -= len(content)
                    total_content += content

                if content_length == 0:
                    message = total_content
                    on_receive_from_debugpy(message)

        except Exception as e:
            log("Failure reading maya's debugpy output: \n" + str(e))
            debugpy_socket.close()
            break


def debugpy_send_loop():
    """
    The loop that waits for items to show in the send queue and prints them.
    Blocks until an item is present
    """

    while True:
        msg = debugpy_send_queue.get()
        if msg is None:
            return
        else:
            try:
                debugpy_socket.send(bytes('Content-Length: {}\r\n\r\n'.format(len(msg)), 'UTF-8'))
                debugpy_socket.send(bytes(msg, 'UTF-8'))
                log('Sent to debugpy:', msg)
            except OSError:
                log("Debug socket closed.")
                return


def on_receive_from_debugpy(message):
    """
    Handles messages going from debugpy to the debugger
    """

    c = json.loads(message)
    seq = int(c.get('request_seq', -1))  # a negative seq will never occur
    cmd = c.get('command', '')

    if cmd == 'configurationDone':
        # When Debugger & debugpy are done setting up, send the code to debug
        if not debug_no_maya:
            send_code_to_maya(run_code)

    # Send responses and events to debugger
    if seq in processed_seqs:
        # Should only be the initialization request
        log("Already processed, debugpy response is:", message)
    else:
        log('Received from debugpy:', message)
        interface.send(message)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(str(e))
        raise e
