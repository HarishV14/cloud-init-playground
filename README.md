# Cloud-Init Playground

Automated and reproducible Ubuntu 24.04 server provisioning using Multipass, cloud-init, Docker, and systemd.

## Technologies Used

- Ubuntu 24.04
- Multipass
- cloud-init
- Docker
- Python HTTP Server
- systemd

## Features

- Automatically installs Git, curl, and Docker.
- Creates a dedicated non-root `testpress` user with Docker group access.
- Creates the environment configuration file `/opt/testpress/app.env`.
- Clones the application source code from GitHub.
- Builds and runs the application inside a Docker container.
- Exposes the HTTP application on port `8080`.
- Supports automatic recovery after VM reboots and unexpected application crashes.

## Getting Started

Clone the repository:

```bash
git clone https://github.com/HarishV14/cloud-init-playground.git
cd cloud-init-playground
```

Create an Ubuntu 24.04 VM using cloud-init:

```bash
multipass launch 24.04 \
  --name cloud-init-lab \
  --cpus 2 \
  --memory 2G \
  --disk 10G \
  --cloud-init cloud-init.yaml
```

### Wait for Provisioning

Wait until cloud-init completes all installation and deployment steps:

```bash
multipass exec cloud-init-lab -- cloud-init status --wait --long
```

Expected output includes:

```text
status: done
extended_status: done
errors: []
recoverable_errors: {}
```

### Verify the Application

Check whether the HTTP application is running:

```bash
multipass exec cloud-init-lab -- curl -i http://localhost:8080/
```

Expected response:

```text
HTTP/1.0 200 OK
Content-Type: text/plain

Hello from Testpress!
```

### Check the Health Endpoint

Verify application health:

```bash
multipass exec cloud-init-lab -- curl http://localhost:8080/health
```

Expected response:

```json
{"status": "ok"}
```

### Verify Docker Container

Check the running container:

```bash
multipass exec cloud-init-lab -- sudo docker ps
```

The `testpress-app` container should appear with a running status and port `8080` exposed.

## Reliability

The application uses Docker's `unless-stopped` restart policy.

This provides:

- **VM reboot recovery:** The Docker service starts automatically through systemd, and the application container starts again.
- **Application crash recovery:** Docker automatically restarts the container if its main process crashes unexpectedly.

Both recovery scenarios were tested successfully.

## Cleanup

Delete the test VM when it is no longer needed:

```bash
multipass delete --purge cloud-init-lab
```

This removes the VM and its virtual disk. It does not delete the local project directory or GitHub repository.

## Verification Results

### Cloud-init Status

Command: `multipass exec cloud-init-lab -- cloud-init status --wait --long`

Actual result:

    status: done
    extended_status: done
    errors: []
    recoverable_errors: {}

### Non-root Docker Access

Command: `multipass exec cloud-init-lab -- sudo -u testpress docker ps`

Result: The testpress-app container was listed successfully without permission errors.

### HTTP Application

Command: `multipass exec cloud-init-lab -- curl -i http://localhost:8080/`

Actual result:

    HTTP/1.0 200 OK
    Content-Type: text/plain

    Hello from Testpress!

### Environment File

Command: `multipass exec cloud-init-lab -- sudo cat /opt/testpress/app.env`

Actual result:

    APP_NAME=Testpress
    APP_PORT=8080
    APP_ENV=production

### Idempotency

The deployment checks whether the repository, image, and container already exist.
Repeated deployment commands did not create duplicate resources.
The existing container retained its ID: `2bf458e37063`.

## Cloud-init Stages

1. Detect: Identifies the instance and data source.
2. Local: Performs early initialization.
3. Network: Configures networking and early setup.
4. Config: Applies configuration modules.
5. Final: Executes final setup commands, including runcmd.

### First Boot vs Every Boot

Cloud-init records completed modules under `/var/lib/cloud/instance/sem/`.
The runcmd deployment normally runs once per instance.
Docker's restart policy starts the application on later VM boots.

## Challenges and Learnings

- Docker permissions: Added testpress to the Docker group.
- YAML permissions: Used `!!str 0644` to ensure a valid string.
- Idempotency: Added existence checks before creating resources.
- Crash recovery: Learned that intentional Docker stops differ from unexpected crashes.

## Scope Note

FFmpeg was requested in the original assignment but was intentionally omitted.

## Continuous Docker Crash Monitoring

The application uses Docker restart policy `unless-stopped` for automatic crash recovery, combined with a Python-based circuit breaker to prevent continuous restart loops.

### Monitoring

- `monitoring/check_restarts.py` continuously listens to Docker start and die events.
- Counts consecutive application crashes.
- Resets the failure count after the container runs for at least 60 seconds.
- Generates a local Ubuntu journal alert after 5 consecutive crashes.
- Opens the circuit breaker after 5 consecutive crashes.
- Changes Docker restart policy to `no` and stops the container during the OPEN state.
- Pauses automatic recovery for 300 seconds (5 minutes).
- Enforces the OPEN state if an external action manually starts the container during cooldown.
- After cooldown, enters HALF-OPEN and attempts application recovery.
- Monitors the application for 60 seconds during HALF-OPEN.
- If stable, closes the circuit and restores Docker restart policy to `unless-stopped`.
- If recovery fails, reopens the circuit and schedules another 300-second cooldown.
- `testpress-monitor.service` manages the monitoring process using systemd.

### Circuit Breaker States

**CLOSED**
- Normal application operation.
- Docker automatically restarts the application after unexpected crashes.
- Consecutive failures are monitored.

**OPEN**
- Activated after 5 consecutive crashes.
- Docker automatic restart is disabled.
- Container is stopped.
- Recovery is paused for 300 seconds.

**HALF-OPEN**
- Application recovery is attempted after the cooldown.
- Docker automatic restart remains disabled during testing.
- Application must remain stable for 60 seconds.
- Successful recovery returns the circuit to CLOSED.
- Failed recovery returns the circuit to OPEN for another 300 seconds.

### Verify Monitoring Service

`multipass exec cloud-init-lab -- sudo systemctl status testpress-monitor.service --no-pager`

### View Monitoring Logs

`multipass exec cloud-init-lab -- sudo journalctl -t testpress-monitor --no-pager -n 20`

### Inspect Circuit Breaker State

`multipass exec cloud-init-lab -- sudo cat /var/lib/testpress-monitor/state.json`

### Verify Docker Restart Policy

`multipass exec cloud-init-lab -- sudo docker inspect --format 'Status={{.State.Status}} RestartPolicy={{.HostConfig.RestartPolicy.Name}}' testpress-app`

Expected restart policies:
- CLOSED: `unless-stopped`
- OPEN: `no`
- HALF-OPEN: `no`

### Simulate an Application Crash

`multipass exec cloud-init-lab -- sudo sh -c 'kill -9 $(docker inspect --format "{{.State.Pid}}" testpress-app)'`

### Verified Test Results

- Fresh Ubuntu 24.04 VM provisioning completed successfully.
- Monitoring service started successfully through systemd.
- Docker automatically restarted the application after unexpected process crashes.
- Five consecutive crashes activated the circuit breaker.
- Docker restart policy changed to `no` and the container stopped.
- An external manual start during OPEN was detected and stopped by the monitor.
- The 300-second cooldown completed and automatic recovery started.
- HALF-OPEN recovery successfully passed the 60-second stability test.
- Circuit returned to CLOSED and Docker restart policy was restored to `unless-stopped`.
- A subsequent crash during HALF-OPEN returned the circuit to OPEN.
- Another 300-second cooldown was scheduled after failed recovery.

### Limitations

- Stability is based on container runtime, not HTTP health checks.
- Alerts are stored locally in the Ubuntu journal.
- Docker event interruptions can affect event detection.
- The monitoring service requires Docker to be available.
- External alert delivery and distributed monitoring are not implemented.
