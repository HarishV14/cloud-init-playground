#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime

CONTAINER = "testpress-app"
THRESHOLD = 5
STABLE_SECONDS = 60
STATE_FILE = Path("/var/lib/testpress-monitor/state.json")


def log(message, priority="info"):
    subprocess.run(
        ["logger", "-t", "testpress-monitor", "-p", f"user.{priority}", message],
        check=True,
    )


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {"failures": 0, "alerted": False, "started_at": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def docker_started_at():
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.StartedAt}}", CONTAINER],
        capture_output=True,
        text=True,
        check=True,
    )
    value = result.stdout.strip()
    if value.startswith("0001-"):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def main():
    state = load_state()

    # Begin monitoring from the current running container.
    # Previous crashes are not counted retroactively.
    state["started_at"] = docker_started_at()
    save_state(state)

    while True:
        command = [
            "docker", "events",
            "--filter", f"container={CONTAINER}",
            "--filter", "event=start",
            "--filter", "event=die",
            "--format", "{{json .}}",
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            text=True,
        )

        for line in process.stdout:
            try:
                event = json.loads(line)
                action = event.get("Action")
                timestamp = event.get("timeNano", 0) / 1_000_000_000

                if action == "start":
                    state["started_at"] = timestamp

                elif action == "die":
                    started = state.get("started_at")

                    if started is None:
                        state["failures"] = 0
                        state["alerted"] = False
                    elif timestamp - started >= STABLE_SECONDS:
                        state["failures"] = 0
                        state["alerted"] = False

                    state["failures"] += 1

                    log(
                        f"{CONTAINER} consecutive failures: {state['failures']}"
                    )

                    if state["failures"] >= THRESHOLD and not state["alerted"]:
                        log(
                            f"ALERT: {CONTAINER} crashed "
                            f"{state['failures']} consecutive times "
                            f"without stable recovery",
                            "warning",
                        )
                        state["alerted"] = True

                    state["started_at"] = None

                save_state(state)

            except (ValueError, KeyError, TypeError) as error:
                log(f"Unable to process Docker event: {error}", "warning")

        process.wait()
        log(
            "Docker event stream disconnected; resetting failure sequence and reconnecting",
            "warning",
        )
        state["failures"] = 0
        state["alerted"] = False
        state["started_at"] = None
        save_state(state)
        time.sleep(2)
        state["started_at"] = docker_started_at()
        save_state(state)


if __name__ == "__main__":
    main()
