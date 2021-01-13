
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
                   fwd ptvsd response              /                                \
                           \                     v                                  v
                            -------  start_maya_debugging()  <--- starts ---  attach_to_maya()
                                        ^           /                               \
                                        res       req                                \
                                          \      v                                   v
                                        ptvsd (in Maya)                   injects ptvsd in Maya


"""

from tempfile import gettempdir
from queue import Queue
from util import *
import socket
import json
import sys
import os


debugger_send_queue = Queue()
processed_seqs = []

maya_cmd_socket = socket.socket()
run_code = ""

ptvsd_send_queue = Queue()
ptvsd_socket: socket.socket

inv_seq = 9223372036854775806  # The maximum int value in Python 2, -1  (hopefully never gets reached)
artificial_seqs = []  # keeps track of which seqs we have sent
waiting_for_pause_event = False


def main():
    """
    Starts the thread to send information to debugger, then remains in a loop
    reading messages from debugger.
    """

    run(debugger_send_loop)

    while True:
        try:
            content_length = 0
            while True:
                header = sys.stdin.readline()
                if header:
                    header = header.strip()
                if not header:
                    break
                if header.startswith(CONTENT_HEADER):
                    content_length = int(header[len(CONTENT_HEADER):])

            if content_length > 0:
                total_content = ""
                while content_length > 0:
                    content = sys.stdin.read(content_length)
                    content_length -= len(content)
                    total_content += content

                if content_length == 0:
                    message = total_content
                    run(on_receive_from_debugger, args=(message,))

        except Exception as e:
            log("Failure reading stdin: " + str(e))
            break


def debugger_send_loop():
    """
    Waits for items to show in the send queue and prints them.
    Blocks until an item is present
    """
    while True:
        msg = debugger_send_queue.get()
        if msg is None:
            break
        else:
            sys.stdout.write('Content-Length: {}\r\n\r\n'.format(len(msg)))
            sys.stdout.write(msg)
            sys.stdout.flush()
            log('Sent to Debugger:', msg)


def on_receive_from_debugger(message):
    """
    Intercept the initialize and attach requests from the debugger
    while ptvsd is being set up
    """

    contents = json.loads(message)

    log('Received from Debugger:', message)

    cmd = contents['command']
    if cmd == 'initialize':
        # Run init request once maya connection is established and send success response to the debugger
        debugger_send_queue.put(json.dumps(json.loads(INITIALIZE_RESPONSE)))  # load and dump to remove indents
        processed_seqs.append(contents['seq'])
        pass
    elif cmd == 'attach':
        # time to attach to maya
        run(attach_to_maya, (contents,))

        # Change arguments to valid ones for ptvsd
        config = contents['arguments']
        new_args = ATTACH_ARGS.format(
            dir=dirname(config['program']).replace('\\', '\\\\'),
            hostname=config['ptvsdhost'],
            port=int(config['ptvsdport']),
            filepath=config['program'].replace('\\', '\\\\')
        )

        contents = contents.copy()
        contents['arguments'] = json.loads(new_args)
        message = json.dumps(contents)  # update contents to reflect new args

        log("New attach arguments loaded:", new_args)

    # Then just put the message in the maya debugging queue
    ptvsd_send_queue.put(message)


def attach_to_maya(contents: dict):
    """
    Defines commands to send to Maya, establishes a connection to its commandPort,
    then sends the code to inject ptvsd
    """

    global run_code
    config = contents['arguments']

    attach_code = ATTACH_TEMPLATE.format(
        ptvsd_path=ptvsd_path,
        hostname=config['ptvsdhost'],
        port=int(config['ptvsdport'])
    )

    run_code = RUN_TEMPLATE.format(
        dir=dirname(config['program']),
        file_name=split(config['program'])[1][:-3] or basename(split(config['program'])[0])[:-3]
    )

    # Connect to given host/port combo
    if not debug_no_maya:
        maya_host, maya_port = config['mayahost'], int(config['mayaport'])
        try:
            maya_cmd_socket.settimeout(3)
            maya_cmd_socket.connect((maya_host, maya_port))
        except:
            run(os._exit, (0,), 1)
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
            maya_cmd_socket.recv(100)
        except:
            pass
        finally:
            log('Successfully attached to Maya')

    # Then start the maya debugging threads
    run(start_debugging, ((config['ptvsdhost'], int(config['ptvsdport'])),))


def send_code_to_maya(code: str):
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
    Connects to ptvsd in Maya, then starts the threads needed to
    send and receive information from it
    """

    log("Connecting to " + address[0] + ":" + str(address[1]))

    global ptvsd_socket
    ptvsd_socket = socket.create_connection(address)

    log("Successfully connected to Maya for debugging. Starting...")

    run(ptvsd_send_loop)  # Start sending requests to ptvsd

    fstream = ptvsd_socket.makefile()

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
                    run(on_receive_from_ptvsd, args=(message,))

        except Exception as e:
            log("Failure reading maya's ptvsd output: \n" + str(e))
            ptvsd_socket.close()
            break


def ptvsd_send_loop():
    """
    The loop that waits for items to show in the send queue and prints them.
    Blocks until an item is present
    """

    while True:
        msg = ptvsd_send_queue.get()
        if msg is None:
            break
        else:
            try:
                ptvsd_socket.send(bytes('Content-Length: {}\r\n\r\n'.format(len(msg)), 'UTF-8'))
                ptvsd_socket.send(bytes(msg, 'UTF-8'))
                log('Sent to ptvsd:', msg)
            except OSError:
                log("Debug socket closed.")
                break


def on_receive_from_ptvsd(message):
    """
    Handles messages going from ptvsd to the debugger
    """

    global inv_seq, artificial_seqs, waiting_for_pause_event

    c = json.loads(message)
    seq = int(c.get('request_seq', -1))  # a negative seq will never occur
    cmd = c.get('command', '')

    if cmd == 'configurationDone':
        # When Debugger & ptvsd are done setting up, send the code to debug
        if not debug_no_maya:
            send_code_to_maya(run_code)      
    
    elif cmd == "variables":
        # Hide the __builtins__ variable (causes errors in the debugger gui)
        vars = c['body'].get('variables')
        if vars:
            toremove = []
            for var in vars:
                if var['name'] in ('__builtins__', '__doc__', '__file__', '__name__', '__package__'):
                    toremove.append(var)
            for var in toremove:
                vars.remove(var)
            message = json.dumps(c)
    
    elif c.get('event', '') == 'stopped' and c['body'].get('reason', '') == 'step':
        # Sometimes (often) ptvsd stops on steps, for an unknown reason.
        # Respond to this with a forced pause to put things back on track.
        log("Stall detected. Sending unblocking command to ptvsd.")
        req = PAUSE_REQUEST.format(seq=inv_seq)
        ptvsd_send_queue.put(req)
        artificial_seqs.append(inv_seq)
        inv_seq -= 1

        # We don't want the debugger to know ptvsd stalled, so pretend it didn't.
        return
    
    elif seq in artificial_seqs:
        # Check for success, then do nothing and wait for pause event to show up
        if c.get('success', False): 
            waiting_for_pause_event = True
        else:
            log("Stall could not be recovered.")
        return
        
    elif c.get('event', '') == 'stopped' and c['body'].get('reason', '') == 'pause' and waiting_for_pause_event:
        # Set waiting for pause event to false and change the reason for the stop to be a step. 
        # Debugging can operate normally again
        waiting_for_pause_event = False
        c['body']['reason'] = 'step'
        message = json.dumps(c)

    if seq in processed_seqs:
        # Should only be the initialization request
        log("Already processed, ptvsd response is:", message)
    else:
        log('Received from ptvsd:', message)
        debugger_send_queue.put(message)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(str(e))
        raise e
