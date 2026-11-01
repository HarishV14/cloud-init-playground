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

The application uses Docker restart policy `unless-stopped` for automatic crash recovery.

### Monitoring

- `monitoring/check_restarts.py` continuously listens to Docker start and die events.
- Counts consecutive application crashes.
- Resets the failure count after the container runs for at least 60 seconds.
- Generates a local Ubuntu journal alert after 5 consecutive crashes.
- Docker continues restarting the application even after an alert.
- `testpress-monitor.service` manages the monitoring process using systemd.

### Verify Monitoring Service

`multipass exec cloud-init-lab -- systemctl status testpress-monitor.service --no-pager`

### View Monitoring Logs

`multipass exec cloud-init-lab -- sudo journalctl -t testpress-monitor --no-pager -n 20`

### Verified Test Results

- Five consecutive crashes generated an alert successfully.
- A sixth crash before 60 seconds increased the counter to 6.
- After 60 seconds of stable runtime, the next crash reset the counter to 1.
- Docker automatically restarted the application after crashes.
- Docker and the monitoring service started successfully after VM reboot.

### Limitations

- Stability is based on container runtime, not HTTP health checks.
- Alerts are stored locally in the Ubuntu journal.
- Docker event interruptions may cause missed failures.
