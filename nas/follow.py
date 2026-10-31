#!/opt/venv/bin/python
"""The Linked Device's always-running service (ADR 0026), which a container has no systemd user
unit to keep (jobs_linux says so). The command is the program's own, so the paths are the ones
`follow` writes and the evening run reads.

Exit 3 means "WhatsApp is off in the config", which the entrypoint takes as nothing to restart.
"""
from __future__ import annotations

import os
import sys

from family_brief import linked_device
from family_brief.config import Config


def main() -> int:
    cfg = Config.load(None)
    if not cfg.whatsapp.enabled:
        print("whatsapp.enabled is false: the Linked Device stays off", flush=True)
        return 3
    command = linked_device.command("follow", cfg)
    if command is None:
        print("the Linked Device can't start: no pinned Node, or no Baileys tree in "
              "/root/ParentRecap/baileys", file=sys.stderr, flush=True)
        return 2
    print("starting: " + " ".join(command), flush=True)
    os.execv(command[0], command)
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main())
