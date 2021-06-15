
"""

This script adds the the containing package as a valid debug adapter in the Debugger's settings

"""

from Debugger.modules.debugger.adapter.adapters import Adapters
from .adapter.maya import Maya

import sublime


if sublime.version() < '4000':
	raise Exception('This version of the Maya adapter requires Sublime Text 4. Use the st3 branch instead.')


def plugin_loaded():
    """
    Add Maya adapter to list of adapters, that way it is recognized by the debugger.
    """

    Adapters.all.append(Maya())
