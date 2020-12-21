# A Debug Adapter for Debugging Python within Maya

This adapter serves as a "middleman" between the Sublime Debugger plugin 
and a DAP implementation for python (ptvsd) injected into Maya.

It intercepts a few Debugger commands to connect the debugger to Maya, and 
otherwise forwards all communications between the debugger and ptvsd normally.