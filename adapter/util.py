
from os.path import abspath, join, dirname, basename, split
from threading import Timer
from datetime import datetime
import json

now = datetime.now()

#  Debugging this adapter
debug = False
debug_no_maya = False
log_file = abspath(join(dirname(__file__), 'log.txt'))

if debug:
    open(log_file, 'w+').close()  # Creates and/or clears the file

ptvsd_path = join(abspath(dirname(__file__)), "python")


# --- Utility functions --- #

def log(msg, json_msg=None):
    if debug:

        if json_msg:
            msg += '\n' + json.dumps(json.loads(json_msg), indent=4)

        with open(log_file, 'a+') as f:
            f.write('\n' + now.strftime("%Y-%m-%d %H:%M:%S") + " - " + msg + '\n')


def run(func, args=None):
    Timer(0.01, func, args=args).start()


# --- Resources --- #
# Used once to ensure ptvsd is imported to Maya

ATTACH_TEMPLATE = """
import sys
ptvsd_module = r"{ptvsd_path}"
if ptvsd_module not in sys.path:
    sys.path.insert(0, ptvsd_module)

import ptvsd

ptvsd.enable_attach(("{hostname}",{port}))

print('\\n --- Successfully attached to Sublime Debugger --- \\n')
"""

# Used to run the module
RUN_TEMPLATE = """
try:
    current_directory = r"{dir}"
    if current_directory not in sys.path:
        sys.path.insert(0, current_directory)
    
    
    print(' --- Debugging {file_name}... --- \\n')
    if '{file_name}' not in globals().keys():
        import {file_name}
    else:
        reload({file_name})
    
    print(' --- Finished debugging {file_name} --- \\n')
except Exception as e:
    print('Error while debugging: ' + str(e))
    raise e
"""

CONTENT_HEADER = "Content-Length: "

INITIALIZE_RESPONSE = """{
    "request_seq": 1,
    "body": {
        "supportsModulesRequest": true,
        "supportsConfigurationDoneRequest": true,
        "supportsDelayedStackTraceLoading": true,
        "supportsDebuggerProperties": true,
        "supportsEvaluateForHovers": true,
        "supportsSetExpression": true,
        "supportsGotoTargetsRequest": true,
        "supportsExceptionOptions": true,
        "exceptionBreakpointFilters": [
            {
                "filter": "raised",
                "default": false,
                "label": "Raised Exceptions"
            },
            {
                "filter": "uncaught",
                "default": true,
                "label": "Uncaught Exceptions"
            }
        ],
        "supportsCompletionsRequest": true,
        "supportsExceptionInfoRequest": true,
        "supportsLogPoints": true,
        "supportsValueFormattingOptions": true,
        "supportsHitConditionalBreakpoints": true,
        "supportsSetVariable": true,
        "supportTerminateDebuggee": true,
        "supportsConditionalBreakpoints": true
    },
    "seq": 1,
    "success": true,
    "command": "initialize",
    "message": "",
    "type": "response"
}"""

ATTACH_ARGS = """{{
    "name": "Maya Python Debugger : Remote Attach",
    "type": "python",
    "request": "attach",
    "port": {port},
    "host": "{hostname}",
    "pathMappings": [
        {{
            "localRoot": "{dir}",
            "remoteRoot": "{dir}"
        }}
    ],
    "MayaDebugFile": "{filepath}"
}}"""

EXEC_COMMAND = """python("execfile('{tmp_file_path}')")"""

