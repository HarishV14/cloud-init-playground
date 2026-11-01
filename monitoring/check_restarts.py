#!/usr/bin/env python3
import json
import os
import selectors
import subprocess
import time
from datetime import datetime
from pathlib import Path

CONTAINER = "testpress-app"
THRESHOLD = 5
STABLE_SECONDS = 60
COOLDOWN_SECONDS = 300
STATE_FILE = Path("/var/lib/testpress-monitor/state.json")


def log(message, priority="info"):
    subprocess.run(
        ["logger", "-t", "testpress-monitor",
         "-p", f"user.{priority}", message],
        check=True,
    )


def docker(*args):
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=True,
    )


def default_state():
    return {
        "mode": "closed",
        "failures": 0,
        "started_at": None,
        "retry_at": None,
        "retry_started_at": None,
        "last_event_ns": 0,
    }


def load_state():
    state = default_state()
    try:
        saved = json.loads(STATE_FILE.read_text())
        if isinstance(saved, dict):
            state.update(saved)
    except (OSError, ValueError):
        pass

    # Migrate from the original monitoring state format.
    if state["mode"] == "closed" and state.get("circuit_open"):
        state["mode"] = "open"
    elif state["mode"] == "closed" and state.get("half_open"):
        state["mode"] = "half-open"

    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    os.replace(temporary, STATE_FILE)


def container_status():
    return docker(
        "inspect", "--format", "{{.State.Status}}", CONTAINER
    ).stdout.strip()


def docker_started_at():
    value = docker(
        "inspect", "--format", "{{.State.StartedAt}}", CONTAINER
    ).stdout.strip()

    if value.startswith("0001-"):
        return None

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    ).timestamp()


def disable_restarts():
    docker("update", "--restart=no", CONTAINER)


def stop_container():
    status = container_status()

    if status in ("running", "restarting", "paused"):
        try:
            docker("stop", "--time", "1", CONTAINER)
        except subprocess.CalledProcessError as error:
            log(f"Docker stop failed: {error}", "warning")


def enforce_open(state):
    disable_restarts()
    stop_container()


def open_circuit(state, reason):
    state["mode"] = "open"
    state["retry_at"] = time.time() + COOLDOWN_SECONDS
    state["retry_started_at"] = None
    state["started_at"] = None
    state["failures"] = THRESHOLD
    save_state(state)

    log(
        f"ALERT: {CONTAINER}: {reason}; "
        f"circuit OPEN for {COOLDOWN_SECONDS} seconds",
        "warning",
    )

    enforce_open(state)


def begin_recovery(state):
    log(f"{CONTAINER}: cooldown expired; beginning recovery")

    disable_restarts()

    # Persist HALF-OPEN before starting Docker, so a monitor
    # restart cannot accidentally enable automatic recovery.
    state["mode"] = "half-open"
    state["retry_at"] = None
    state["retry_started_at"] = None
    save_state(state)

    try:
        if container_status() != "running":
            docker("start", CONTAINER)

        started_at = docker_started_at()

        if container_status() != "running" or started_at is None:
            raise RuntimeError("Container did not remain running")

        state["retry_started_at"] = started_at
        state["started_at"] = started_at
        save_state(state)

        log(
            f"{CONTAINER}: HALF-OPEN; testing "
            f"{STABLE_SECONDS}-second stability"
        )

    except (subprocess.CalledProcessError, RuntimeError) as error:
        open_circuit(state, f"recovery start failed: {error}")


def check_state(state):
    mode = state["mode"]

    if mode == "open":
        if time.time() >= (state.get("retry_at") or 0):
            begin_recovery(state)
        else:
            enforce_open(state)
        return

    if mode != "half-open":
        return

    started = state.get("retry_started_at")

    if container_status() != "running":
        open_circuit(state, "recovery crashed before stability")
        return

    if started is None:
        started = docker_started_at()
        if started is None:
            open_circuit(state, "recovery start time unavailable")
            return
        state["retry_started_at"] = started
        save_state(state)

    actual_start = docker_started_at()

    if actual_start is None or abs(actual_start - started) > 0.01:
        open_circuit(state, "container restarted during recovery")
        return

    if time.time() - started >= STABLE_SECONDS:
        # Confirm the container is still running before
        # restoring Docker's automatic restart policy.
        if container_status() != "running":
            open_circuit(state, "recovery stopped at stability check")
            return

        docker("update", "--restart=unless-stopped", CONTAINER)

        state["mode"] = "closed"
        state["failures"] = 0
        state["started_at"] = started
        state["retry_started_at"] = None
        state["retry_at"] = None
        save_state(state)

        log(
            f"{CONTAINER}: stable for {STABLE_SECONDS} seconds; "
            "circuit CLOSED; automatic restarts restored"
        )


def handle_event(state, event):
    action = event.get("Action")
    event_ns = int(event.get("timeNano") or 0)

    if not event_ns:
        return

    if event_ns <= state.get("last_event_ns", 0):
        return

    state["last_event_ns"] = event_ns
    timestamp = event_ns / 1_000_000_000

    if state["mode"] == "open":
        save_state(state)
        return

    if state["mode"] == "half-open":
        started = state.get("retry_started_at")

        if action == "die" and (
            started is None or timestamp >= started
        ):
            open_circuit(state, "crashed during HALF-OPEN recovery")
        else:
            save_state(state)
        return

    if action == "start":
        state["started_at"] = timestamp

    elif action == "die":
        started = state.get("started_at")

        if started is not None and timestamp - started >= STABLE_SECONDS:
            state["failures"] = 0

        state["failures"] += 1
        state["started_at"] = None

        log(
            f"{CONTAINER} consecutive failures: {state['failures']}"
        )

        if state["failures"] >= THRESHOLD:
            open_circuit(state, "five consecutive crashes")
            return

    save_state(state)


def main():
    state = load_state()

    if state["mode"] == "open":
        enforce_open(state)
    elif state["mode"] == "half-open":
        disable_restarts()
        check_state(state)
    else:
        state["started_at"] = docker_started_at()
        save_state(state)

    while True:
        process = None
        selector = selectors.DefaultSelector()

        try:
            process = subprocess.Popen(
                [
                    "docker", "events",
                    "--filter", f"container={CONTAINER}",
                    "--filter", "event=start",
                    "--filter", "event=die",
                    "--format", "{{json .}}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )

            selector.register(process.stdout, selectors.EVENT_READ)
            buffer = b""

            while process.poll() is None:
                for key, _ in selector.select(timeout=1):
                    chunk = os.read(key.fd, 65536)

                    if not chunk:
                        break

                    buffer += chunk

                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)

                        try:
                            handle_event(
                                state, json.loads(line.decode("utf-8"))
                            )
                        except (ValueError, TypeError) as error:
                            log(
                                f"Invalid Docker event: {error}",
                                "warning",
                            )

                check_state(state)

            log("Docker event stream disconnected; reconnecting", "warning")

        except (OSError, subprocess.CalledProcessError) as error:
            log(f"Monitoring error: {error}", "warning")

        finally:
            selector.close()

            if process is not None:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        # Preserve the failure count and circuit state.
        time.sleep(2)


if __name__ == "__main__":
    main()
