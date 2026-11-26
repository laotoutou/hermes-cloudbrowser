# Cloudbrowser for Hermes Agent

Run each Hermes browser session on a separate remote Chrome desktop. This community plugin was prepared on behalf of Cloudbrowser. The [virtual browser setup guide](https://cloudbrowser.tv/virtual-browser) explains the hosted desktop, its live view, and browser-scoped CDP connections.

Install this directory with `hermes plugins install /path/to/browser-cloudbrowser`. Enable `browser-cloudbrowser`, then select Cloudbrowser in `hermes tools` under Browser Automation and provide a Cloudbrowser API key. The browser tool requires Python 3.14 in Hermes Agent 0.23.4. Use a workspace intended for automation.

The plugin creates a new desktop for the session and asks Cloudbrowser to delete it when Hermes ends the session. Browser state stays in that session's desktop until deletion. Closing the session discards its local browser data. If Hermes is terminated abruptly or cleanup fails, open the Cloudbrowser console and delete any remaining desktop whose name starts with `Hermes`.

## Network and credential use

The plugin reads the workspace key through the active Hermes profile. It sends the key to `https://cloudbrowser.tv/api/v1` to create and remove browser sessions. Hermes receives a browser-scoped WebSocket URL with full control of the new desktop. Treat that URL as a credential. Browser navigation uses the remote Cloudbrowser desktop and consumes the workspace's browser time. Usage and concurrency limits follow the Cloudbrowser plan. The plugin does not start child processes, install dependencies, or collect telemetry.

## Verification

The Hermes Agent 0.23.4 plugin validator passed. Local tests covered creation, idempotent retry, and cleanup. An end-to-end test used a local Cloudbrowser API fixture and a disposable Chrome over TLS with the actual Hermes `browser_exec` tool. Production API compatibility has yet to be verified.
