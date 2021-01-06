
"""

This script adds the the containing package as a valid debug adapter in the Debugger's settings

"""

from os.path import join, abspath, dirname
import sublime
import json


adapter_type = "mayapy"  # NOTE: type must be unique to each adapter
package_path = dirname(abspath(__file__))
adapter_path = join(package_path, "adapter")
json_path = join(package_path, "sublime_debugger.json")


# The version is only used to display in the GUI
version = "1.0"

# You can have several configurations here depending on your adapter's offered functionalities,
# but they all need a "label", "description", and "body"
config_snippets = [
    {
        "label": "Maya: Python Debugging",
        "description": "Run and Debug Python code in Maya",
        "body": {
            "name": "Maya: Python Debugging",  
            "type": adapter_type,
            "program": "\${file\}",
            "request": "attach",  # can only be attach or launch
            "mayahost": "\${mayahost\}",  # The host/port over which maya commands will be sent
            "mayaport": "\${mayaport\}",
            "ptvsdhost": "\${ptvsdhost\}", # The host/port used to communicate with ptvsd in maya
            "ptvsdport": "\${ptvsdport\}"
        }
    },
]

# The settings used by the Debugger to run the adapter.
# Variables under "settings" will be used to fill out configurations at runtime
settings = {
    "type": adapter_type,
    "command": ["python", adapter_path],
    "install info": json_path,
    "settings": {
        # These must all be strings.
        # Convert them back to bools/ints in your adapter when recieved
        "mayahost": "localhost",
        "mayaport": "7001",
        "ptvsdhost": "localhost",
        "ptvsdport": "7002",
    }
}

# Write contents to json immediately
with open(json_path, 'w') as f:
    json.dump({
        "version": version,
        "configurationSnippets": config_snippets
    }, f)


def plugin_loaded():

    # Add adapter to debugger settings for it to be recognized
    debugger_settings = sublime.load_settings('debugger.sublime-settings')
    adapters_custom = debugger_settings.get('adapters_custom', {})

    adapters_custom[adapter_type] = settings

    debugger_settings.set('adapters_custom', adapters_custom)
    sublime.save_settings('debugger.sublime-settings')


def plugin_unloaded():
    """This is all done every unload just in case this adapter is being uninstalled"""

    # Remove entry from debugger settings
    debugger_settings = sublime.load_settings('debugger.sublime-settings')
    adapters_custom = debugger_settings.get('adapters_custom', {})

    adapters_custom.pop(adapter_type, "")

    debugger_settings.set('adapters_custom', adapters_custom)
    sublime.save_settings('debugger.sublime-settings')
