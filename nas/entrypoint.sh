#!/bin/sh
# Parent Recap's evening job on the NAS. There is no systemd in a container, so this waits for the
# Brief's hour itself and runs `parent-recap run` once a day, the same command the systemd timer
# runs on a Linux server (ADR 0029). `docker exec parent-recap parent-recap run` runs it by hand at
# any time.
set -u

DAILY_HOUR="${DAILY_HOUR:-20}"
DAILY_MINUTE="${DAILY_MINUTE:-0}"

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"; }

say "Parent Recap on the NAS: Brief at ${DAILY_HOUR}:$(printf '%02d' "$DAILY_MINUTE") $TZ"
say "config: $(parent-recap --help >/dev/null 2>&1 && echo present) | codex: $(command -v codex || echo MISSING)"
say "wilma: $(test -x /root/ParentRecap/wilma/bin/wilma && echo present || echo MISSING)"

# The setup page, which is the only way a Household without a Mac sets Parent Recap up: it asks
# for the kids, Wilma, Gmail, the ChatGPT sign-in, WhatsApp's code and MyClub's link, and saves the
# config the evening run reads. Reach it on SETUP_PORT (mapped to the same port outside) until
# SETUP_IDLE_MINUTES without a request, or for good at 0. The evening job and the Linked Device
# wait until the page has saved a config, so this mode serves the page alone.
if [ "${MODE:-daily}" = "setup" ]; then
    say "MODE=setup: serving the setup page on ${SETUP_PUBLIC_URL:-port ${SETUP_PORT:-8090}}"
    exec parent-recap setup page --bind "${SETUP_BIND:-0.0.0.0}" --port "${SETUP_PORT:-8090}"
fi

# The Linked Device's service, which keeps the picked groups' messages in the store the evening
# run reads. A container has no systemd unit to keep it, so this keeps it: restarted when it
# falls over, and left alone when the config has WhatsApp off (exit 3).
#
# The service execs into its Node, so this subshell owns it. It waits on the child rather than
# running it in the foreground, so that a stop can kill it: an orphaned Node would keep its
# WhatsApp link open, and the server ends the link when the next one connects (401). Docker sends
# the stop to this script alone, so nothing else would reach it.
#
# A link that ended stays ended until the setup page pairs it again, so this doesn't start the
# service on one: connecting again would only be refused, and it would collide with the page's
# own pairing, which ends the link a second time.
LINK_STATUS=/root/ParentRecap/linked-device/status.json
LINK_AUTH=/root/ParentRecap/linked-device/auth

awaiting_pairing() {
    if [ -f "$LINK_STATUS" ]; then
        grep -q '"paired"[[:space:]]*:[[:space:]]*true' "$LINK_STATUS" && return 1
        return 0
    fi
    # No status file yet: follow it only on a pairing already there.
    [ -d "$LINK_AUTH" ] && [ -n "$(ls -A "$LINK_AUTH" 2>/dev/null)" ] && return 1
    return 0
}

(
    child=
    waiting=
    stop() {
        [ -n "$child" ] && kill -TERM "$child" 2>/dev/null
        [ -n "$child" ] && wait "$child" 2>/dev/null
        exit 0
    }
    trap stop INT TERM
    while true; do
        if awaiting_pairing; then
            [ -z "$waiting" ] && say "WhatsApp needs pairing: open the setup page's WhatsApp step to link it again"
            waiting=1
            sleep 30 &
            wait $!  # a stop interrupts the pause too
            continue
        fi
        waiting=
        parent-recap-follow &
        child=$!
        wait "$child"
        code=$?
        if [ "$code" -eq 3 ]; then
            say "WhatsApp is off in the config: no Linked Device"
            break
        fi
        say "the Linked Device stopped (exit $code); restarting in 30s"
        sleep 30 &
        wait $!  # a stop interrupts the pause too
    done
) &
LINKED_PID=$!
trap 'kill "$LINKED_PID" 2>/dev/null' INT TERM

# The setup page, kept up beside the evening job so a Household can change its answers without
# stopping the Brief: it writes the config the job reads, and only while someone is on it. It runs
# here rather than in a second container because both write the Linked Device's pairing and its
# store, which two of them may not. SETUP_WEB=0 keeps it off; the address, with its one-time code,
# is in this log. `MODE=setup` above serves the page alone, which a Household with no config yet
# needs: the evening job can't start without one.
if [ "${SETUP_WEB:-1}" != "0" ]; then
    parent-recap setup page --bind "${SETUP_BIND:-0.0.0.0}" --port "${SETUP_PORT:-8090}" &
    SETUP_PID=$!
    trap 'kill "$LINKED_PID" "$SETUP_PID" 2>/dev/null' INT TERM
fi

if [ "${RUN_ON_START:-0}" = "1" ]; then
    say "RUN_ON_START=1: one run now${RUN_ARGS:-}"
    # shellcheck disable=SC2086
    parent-recap run ${RUN_ARGS:-} || say "that run failed with exit $?"
fi

while true; do
    now=$(date +%s)
    target=$(date -d "today ${DAILY_HOUR}:${DAILY_MINUTE}" +%s)
    if [ "$target" -le "$now" ]; then
        target=$(date -d "tomorrow ${DAILY_HOUR}:${DAILY_MINUTE}" +%s)
    fi
    say "next run at $(date -d "@${target}" '+%Y-%m-%d %H:%M %Z')"
    sleep $((target - now))

    say "=== parent-recap run ==="
    # shellcheck disable=SC2086
    parent-recap run ${RUN_ARGS:-}
    say "=== run finished with exit $? ==="
done
