# A Debug Adapter for Debugging Python within Maya

This adapter serves as a "middleman" between the Sublime Debugger plugin 
and a DAP implementation for python (ptvsd) injected into Maya.

It intercepts a few DAP requests to establish a connection between the debugger and Maya, and 
otherwise forwards all communications between the debugger and ptvsd normally.

### Installation

To install from repo,
- Open Sublime
- Install the "Debugger" plugin with Package Control if not done already
- In the "Preferences" menu, select "Browse Packages..."
- Clone this repository into the folder opened by Sublime

### Use

- Open the project you want to debug
    - If the debugger isn't open, select "Open" in the "Debugger" menu option
    - If it still doesn't open, ensure your project settings (Project -> Edit Project) are not empty
- Under the "Debugger" menu, select "Add or Select Configuration"
- Select "Add Configuration" from the suggestions
- There should be a "Maya: Python Debugging" option, click on it
- You should have your project settings automatically opened, edited with the configuration
- Save your project settings
- Go back to Debugger -> Add or Select Configuration, and select Maya: Python Debugging

The Maya Adapter should now be functional just by pressing play. It will guide you with how to connect to Maya itself.
