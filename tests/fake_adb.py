#!/usr/bin/env python3
"""Explicit test fixture. Never used by the production launcher."""

import base64
import json
import os
from pathlib import Path
import shlex
import sys

args = sys.argv[1:]
log = os.environ.get("FIRETV_TEST_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\n")
if args[:1] == ["-s"]:
    args = args[2:]
command = args[0]
state = os.environ.get("FIRETV_TEST_STATE", "device")
if command == "version":
    print("Android Debug Bridge version 1.0.41 (test fixture)")
elif command == "devices":
    print(f"List of devices attached\n192.168.1.50:5555\t{state} product:firetv model:Fire_TV_TEST device:test")
elif command == "connect":
    print("connected to " + args[1])
elif command == "disconnect":
    print("disconnected " + args[1])
elif command == "get-state":
    print(state)
elif command == "install":
    print(os.environ.get("FIRETV_TEST_INSTALL", "Success"))
elif command == "uninstall":
    print("Success")
elif command == "push":
    print("1 file pushed")
elif command == "pull":
    Path(args[2]).write_bytes(b"file from test fixture\n")
    print("1 file pulled")
elif command == "exec-out":
    sys.stdout.buffer.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="))
elif command == "shell":
    remote = shlex.split(args[1])
    if remote[0] == "getprop":
        print("[ro.product.model]: [Fire TV TEST]\n[ro.build.version.release]: [9]\n[ro.build.display.id]: [Fire OS test]\n[ro.product.manufacturer]: [Amazon]")
    elif remote[0] == "df":
        print("Filesystem Size Used Avail Use% Mounted on\n/dev/fuse 5G 2G 3G 40% /sdcard")
    elif remote[:3] == ["pm", "list", "packages"]:
        print("package:org.example.player\npackage:org.example.launcher")
        if "-3" not in remote:
            print("package:com.amazon.tv.launcher")
    elif remote[:2] == ["cmd", "package"]:
        if "query-activities" in remote:
            print("1 activities found:\n  Activity #0:\n    priority=1 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n    org.example.launcher/.MainActivity")
        elif "-p" in remote:
            package = remote[remote.index("-p") + 1]
            print(package + "/.MainActivity")
        else:
            print("com.amazon.tv.launcher/.MainActivity")
    elif remote[:2] == ["sh", "-c"]:
        if remote[3] == "firetv-list":
            sys.stdout.buffer.write(b"directory\0Download\0file\0notes.txt\0file\0a'$(touch owned).txt\0link\0shortcut\0")
        elif remote[3] == "firetv-exists":
            if os.environ.get("FIRETV_TEST_EXISTS"):
                print("exists")
    elif remote[:2] == ["am", "start"]:
        print("Starting: Intent { ... }")
    elif remote[0] in ("input", "test"):
        pass
    else:
        print("unsupported fixture command", file=sys.stderr)
        sys.exit(1)
else:
    print("unsupported fixture command", file=sys.stderr)
    sys.exit(1)
