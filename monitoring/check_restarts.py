#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path

CONTAINER = "testpress-app"
THRESHOLD = 5
WINDOW_SECONDS = 300
STATE_FILE = Path("/var/lib/testpress-monitor/state.json")


def docker_restart_count():
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.RestartCount}}", CONTAINER],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip())


def log(message, priority="info"):
    subprocess.run(
        ["logger", "-t", "testpress-monitor", "-p", f"user.{priority}", message],
        check=True,
    )


def main():
    now = time.time()
    current = docker_restart_count()

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    else:
        state = {"last_count": current, "events": [], "alerted": False}

    previous = state["last_count"]

    if current < previous:
        state = {"last_count": current, "events": [], "alerted": False}
        previous = current

    events = [
        event for event in state["events"]
        if now - event["time"] <= WINDOW_SECONDS
    ]

    if current > previous:
        events.append({"time": now, "count": current - previous})

    recent_restarts = sum(event["count"] for event in events)

    if recent_restarts >= THRESHOLD and not state["alerted"]:
        log(
            f"ALERT: {CONTAINER} restarted {recent_restarts} times "
            f"within 5 minutes",
            "warning",
        )
        state["alerted"] = True

    if recent_restarts < THRESHOLD:
        state["alerted"] = False

    state.update({
        "last_count": current,
        "events": events,
    })

    STATE_FILE.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
