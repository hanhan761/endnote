# endnote

Deploy only to the authorized 4090 target (workstation), never wenshanzhike-edge.
Use hidden noninteractive child processes on Windows. Build/test/package locally;
production activates a checksum-verified immutable release.
Never commit credentials, databases, logs, real recipient addresses, or populated env files.
Public callers submit declarative rules and experiment events, never executable code,
URLs to fetch, or server commands.
Run `python -m unittest discover -s tests -v` before publishing.
