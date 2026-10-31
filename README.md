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
- Creates a dedicated `testpress` system user.
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
