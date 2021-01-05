# A Debug Adapter for Debugging Python within Maya

This adapter serves as a "middleman" between the Sublime Debugger plugin 
and a DAP implementation for python (ptvsd) injected into Maya.

It intercepts a few DAP requests to establish a connection between the debugger and Maya, and 
otherwise forwards all communications between the debugger and ptvsd normally.
