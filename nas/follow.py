#!/opt/venv/bin/python
"""The Linked Device's always-running service (ADR 0026), which a container has no systemd user
unit to keep (jobs_linux says so). The command is the program's own, so the paths are the ones
`follow` writes and the evening run reads.

One process per WhatsApp number: a Household with a second account pairs each separately, and
WhatsApp ends a link when two connections use the same pairing, so they can't share one. A child
that falls over is started again after a pause; one that ends because WhatsApp ended its link is
started again too, which waits for a new pairing.

Exit 3 means "WhatsApp is off in the config", which the entrypoint takes as nothing to restart.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import time

from family_brief import linked_device
from family_brief.config import Config

RESTART_SECONDS = 15  # how long a number that fell over waits before being started again
STOP_SECONDS = 25  # how long stopping waits for the numbers to close their links


def main() -> int:
    cfg = Config.load(None)
    if not cfg.whatsapp.enabled:
        print("whatsapp.enabled is false: the Linked Device stays off", flush=True)
        return 3
    accounts = [account for account, _ in cfg.whatsapp.all_accounts()]
    if not accounts:
        print("no WhatsApp group is picked: the Linked Device stays off", flush=True)
        return 3

    commands: dict[str, list[str]] = {}
    for account in accounts:
        command = linked_device.command("follow", cfg, account=account)
        if command is None:
            print("the Linked Device can't start: no pinned Node, or no Baileys tree in "
                  "/root/ParentRecap/baileys", file=sys.stderr, flush=True)
            return 2
        commands[account] = command
        print(f"starting account {account}: " + " ".join(command), flush=True)

    children: dict[str, subprocess.Popen] = {}

    def stop(signum, frame) -> None:  # noqa: ANN001 - the signal module's own signature
        """Lets every number close its link before this exits, which is what keeps the pairing."""
        for child in children.values():
            if child.poll() is None:
                child.terminate()
        deadline = time.time() + STOP_SECONDS
        for child in children.values():
            try:
                child.wait(max(0.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                child.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    later = {account: 0.0 for account in accounts}
    while True:
        now = time.time()
        for account in accounts:
            child = children.get(account)
            if child is not None and child.poll() is None:
                continue
            if child is not None and now < later[account]:
                continue
            if child is not None:
                print(f"account {account} ended with {child.returncode}; starting it again",
                      flush=True)
            children[account] = subprocess.Popen(commands[account])
            later[account] = time.time() + RESTART_SECONDS
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
