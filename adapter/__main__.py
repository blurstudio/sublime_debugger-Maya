
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
import time
import sys
import os


# Globals
signal_location = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'finished.txt')
last_seq = -1

debugger_send_queue = Queue()
processed_seqs = []

maya_cmd_socket = socket.socket()
run_code = ""

ptvsd_send_queue = Queue()
ptvsd_socket: socket.socket


# Avoiding stalls
inv_seq = 9223372036854775806  # The maximum int value in Python 2, -1  (hopefully never gets reached)
artificial_seqs = []  # keeps track of which seqs we have sent
waiting_for_pause_event = False

avoiding_continue_stall = False
stashed_event = None

disconnecting = False


def main():
    """
    Starts the thread to send information to debugger, then remains in a loop
    reading messages from debugger.
    """

    if os.path.exists(signal_location):
        os.remove(signal_location)

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
                    on_receive_from_debugger(message)

        except Exception as e:
            log("Failure reading stdin: " + str(e))
            return


def debugger_send_loop():
    """
    Waits for items to show in the send queue and prints them.
    Blocks until an item is present
    """
    while True:
        msg = debugger_send_queue.get()
        if msg is None:
            return
        else:
            try:
                sys.stdout.write('Content-Length: {}\r\n\r\n'.format(len(msg)))
                sys.stdout.write(msg)
                sys.stdout.flush()
                log('Sent to Debugger:', msg)
            except Exception as e:
                log("Failure writing to stdout (normal on exit):" + str(e))
                return


def on_receive_from_debugger(message):
    """
    Intercept the initialize and attach requests from the debugger
    while ptvsd is being set up
    """

    global last_seq, avoiding_continue_stall

    contents = json.loads(message)
    last_seq = contents.get('seq')

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
            hostname=config['ptvsd']['host'],
            port=int(config['ptvsd']['port']),
            filepath=config['program'].replace('\\', '\\\\')
        )

        contents = contents.copy()
        contents['arguments'] = json.loads(new_args)
        message = json.dumps(contents)  # update contents to reflect new args

        log("New attach arguments loaded:", new_args)
    
    elif cmd == 'continue':
        avoiding_continue_stall = True

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
        hostname=config['ptvsd']['host'],
        port=int(config['ptvsd']['port'])
    )

    run_code = RUN_TEMPLATE.format(
        dir=dirname(config['program']),
        file_name=split(config['program'])[1][:-3] or basename(split(config['program'])[0])[:-3],
        signal_location=signal_location.replace('\\', '\\\\')
    )

    log("RUN: \n" + run_code)

    # Connect to given host/port combo
    if not debug_no_maya:
        maya_host, maya_port = config['maya']['host'], int(config['maya']['port'])
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
            maya_cmd_socket.recv(128)
        except:
            pass
        finally:
            log('Successfully attached to Maya')

    # Then start the maya debugging threads
    run(start_debugging, ((config['ptvsd']['host'], int(config['ptvsd']['port'])),))

    # And finally wait for the signal from ptvsd that debugging is done
    run(wait_for_signal)


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


def wait_for_signal():
    """
    Waits for the signal location to exist, which means debugging is done.
    Deletes the signal location and prepares this adapter for disconnect.
    """

    global disconnecting

    while True:
        
        if os.path.exists(signal_location):
            log('--- FINISHED DEBUGGING ---')

            os.remove(signal_location)
            run(disconnect)


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
                    on_receive_from_ptvsd(message)

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
            return
        else:
            try:
                ptvsd_socket.send(bytes('Content-Length: {}\r\n\r\n'.format(len(msg)), 'UTF-8'))
                ptvsd_socket.send(bytes(msg, 'UTF-8'))
                log('Sent to ptvsd:', msg)
            except OSError:
                log("Debug socket closed.")
                return


def on_receive_from_ptvsd(message):
    """
    Handles messages going from ptvsd to the debugger
    """

    global inv_seq, artificial_seqs, waiting_for_pause_event, avoiding_continue_stall, stashed_event

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
        
    elif waiting_for_pause_event and c.get('event', '') == 'stopped' and c['body'].get('reason', '') == 'pause':
        # Set waiting for pause event to false and change the reason for the stop to be a step. 
        # Debugging can operate normally again
        waiting_for_pause_event = False
        c['body']['reason'] = 'step'
        message = json.dumps(c)
    
    elif avoiding_continue_stall and c.get('event', '') == 'stopped' and c['body'].get('reason', '') == 'breakpoint':
        # temporarily hold this message to send only after the continued event is received
        log("Temporarily stashed: ", message)
        stashed_event = message
        return
    
    elif avoiding_continue_stall and c.get('event', '') == 'continued':
        avoiding_continue_stall = False

        if stashed_event:
            log('Received from ptvsd:', message)
            debugger_send_queue.put(message)

            log('Sending stashed message:', stashed_event)
            debugger_send_queue.put(stashed_event)

            stashed_event = None
            return

    # Send responses and events to debugger
    if seq in processed_seqs:
        # Should only be the initialization request
        log("Already processed, ptvsd response is:", message)
    else:
        log('Received from ptvsd:', message)
        debugger_send_queue.put(message)


def disconnect():
    """
    Clean things up by unblocking (and killing) all threads, then exit
    """

    # Unblock and kill the send threads
    debugger_send_queue.put(None)
    while debugger_send_queue.qsize() != 0:
        time.sleep(0.1)
    
    ptvsd_send_queue.put(None)
    while ptvsd_send_queue.qsize() != 0:
        time.sleep(0.1)

    # Close ptvsd socket and stdin so readline() functions unblock
    ptvsd_socket.close()
    sys.stdin.close()

    # exit all threads
    os._exit(0)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(str(e))
        raise e
