# Implementation Report — Cloud-Init Playground

**Assignment:** Testpress DevOps Hands-On  
**Project:** Cloud-Init Playground  
**Operating System:** Ubuntu 24.04 LTS  
**Virtualization:** Multipass on macOS  
**Technologies:** Cloud-init, Docker, Python, systemd, Git, Linux  
**Implementation Status:** Completed and tested, with the scope exception noted below.


---

## 1. Project Overview

The objective of this assignment was to automate the provisioning of a Linux server using cloud-init, reducing the need for manual installation and configuration.

I implemented a reproducible Ubuntu server setup using Multipass and cloud-init. When a new virtual machine is launched, the provisioning configuration automatically installs the required packages, creates an application user, configures environment variables, retrieves the application source code, builds a Docker image, and starts the application.

I also implemented automatic application recovery and a continuous monitoring service that detects repeated container crashes. The monitoring service uses a circuit-breaker approach: after five consecutive crashes, it pauses Docker recovery for five minutes, then attempts recovery and checks whether the application remains stable.

The complete provisioning and deployment process is defined in code and maintained in a GitHub repository.

## 2. Objectives

The main objectives were:


1. Provision an Ubuntu 24.04 virtual machine automatically.
2. Install the required system packages.
3. Create a dedicated non-root application user.
4. Configure the application environment.
5. Deploy a sample application using Docker.
6. Automatically recover from application crashes and server reboots.
7. Detect five consecutive application failures, pause automatic recovery, and retry after a cooldown.
8. Verify the complete implementation through practical testing, including successful and failed recovery attempts.

## 3. Tools and Technologies

| Technology | Purpose |
|------------|---------|
| Multipass  | Create and manage Ubuntu virtual machines on macOS |
| Ubuntu 24.04 | Linux operating system for the server |
| Cloud-init | Automate server configuration during first boot |
| Git        | Retrieve and manage application source code |
| Docker     | Package and run the application in a container |
| Python     | Implement the sample HTTP server and monitoring logic |
| systemd    | Manage Docker and the monitoring service |
| journald   | Store application monitoring alerts locally |

## 4. Architecture

The application follows this architecture:

```text
macOS Host
    |
    | Multipass launch
    v
Ubuntu 24.04 Virtual Machine
    |
    v
Cloud-init Configuration
    |
    +-- Install Git, curl, Docker
    |
    +-- Create testpress user
    |
    +-- Create environment file
    |
    +-- Clone GitHub repository
    |
    +-- Build Docker image
    |
    +-- Start application container
    |
    +-- Enable monitoring service
              |
              v
        Docker Event Monitor
              |
        Listen for start/die
              |
        Count consecutive crashes
              |
        Five consecutive crashes?
              |
              v
        Circuit Breaker: OPEN
              |
        Disable Docker restart policy
        Stop application container
        Log alert to Ubuntu journal
              |
        Wait 300 seconds
              |
              v
        Circuit Breaker: HALF-OPEN
              |
        Attempt application recovery
        Observe for 60 seconds
              |
         +----+----+
         |         |
      Stable    Crashes/fails
         |         |
         v         v
       CLOSED     OPEN
    Restore       Wait another
    unless-stopped 300 seconds
```

The responsibilities are separated:

* **Cloud-init** handles initial server provisioning.
* **Docker** runs the application and provides automatic restarts while the circuit is CLOSED.
* **systemd** manages the monitoring process.
* **Python monitoring script** detects consecutive failures and controls the circuit-breaker states.
* **Ubuntu journal** records alerts and monitoring events.

## 5. Project Structure

```text
cloud-init-playground/
|
|-- cloud-init.yaml
|-- README.md
|
|-- app/
|   |-- Dockerfile
|   |-- server.py
|
|-- monitoring/
|   |-- check_restarts.py
|   |-- testpress-monitor.service
|   |-- testpress-monitor.timer
```

The `testpress-monitor.timer` file is a legacy implementation artifact. The current deployment uses a continuous monitoring service instead of timer-based polling.

## 6. Server Provisioning Using Cloud-Init

Cloud-init is a tool that automatically configures a cloud or virtual machine when it is initialized.

Instead of manually logging into Ubuntu and installing packages, I defined the configuration in `cloud-init.yaml`.

### 6.1 Package Installation

The configuration installs:

```yaml
package_update: true

packages:
  - git
  - curl
  - docker.io
```

This updates package information and installs the required software.

### 6.2 User Configuration

A dedicated user named `testpress` is created:

```yaml
groups:
  - docker

users:
  - default
  - name: testpress
    gecos: Testpress Application User
    shell: /bin/bash
    groups:
      - docker
```

The user belongs to the Docker group, allowing Docker commands without using `sudo`.

**Security consideration:** Docker group membership provides privileges comparable to root access and should only be granted to trusted users.

### 6.3 Environment Configuration

Cloud-init creates the file:

`/opt/testpress/app.env`

Its contents are:

```env
APP_NAME=Testpress
APP_PORT=8080
APP_ENV=production
```

The file is passed to the Docker container during deployment.

The current configuration uses file permissions `0644` and contains only non-sensitive settings. Secrets should not be stored using these permissions.

### 6.4 Application Deployment

Cloud-init performs the following operations:


1. Enables and starts Docker.
2. Clones the project from GitHub.
3. Builds the application Docker image.
4. Starts the application container.
5. Installs and enables the monitoring service.

The container is configured with:

```bash
docker run -d \
  --env-file /opt/testpress/app.env \
  --name testpress-app \
  --restart unless-stopped \
  -p 8080:8080 \
  testpress-app:v1
```

The application runs on port `8080`.

## 7. Launching the Virtual Machine

The Ubuntu virtual machine was created using Multipass:

```bash
multipass launch 24.04 \
  --name cloud-init-lab \
  --cpus 2 \
  --memory 2G \
  --disk 10G \
  --cloud-init cloud-init.yaml
```

The command creates an Ubuntu 24.04 VM and supplies the provisioning configuration during initialization.

After launching the instance, I checked the provisioning status:

```bash
multipass exec cloud-init-lab -- \
  cloud-init status --wait --long
```

### Actual Result

```text
status: done
extended_status: done
errors: []
recoverable_errors: {}
```

**Result: PASS**

Cloud-init completed successfully without reported errors.

## 8. Application Verification

The application is a simple Python HTTP server running inside Docker.

It provides two endpoints.

### 8.1 Root Endpoint

Command:

```bash
multipass exec cloud-init-lab -- \
  curl -i http://localhost:8080/
```

Response:

```text
HTTP/1.0 200 OK

Hello from Testpress!
```

**Result: PASS**

### 8.2 Health Endpoint

Command:

```bash
multipass exec cloud-init-lab -- \
  curl -i http://localhost:8080/health
```

Verified response:

```text
HTTP/1.0 200 OK
Content-Type: application/json

{"status": "ok"}
```

**Result: PASS**

This confirms that the application is responding successfully to HTTP requests.

## 9. Automatic Application Recovery

To improve application reliability, I configured Docker with the following restart policy:

```bash
--restart unless-stopped
```

This allows Docker to restart the container automatically after an unexpected application crash while the circuit breaker is CLOSED.

It also allows the container to start again when Docker starts after a VM reboot, provided the container was not intentionally stopped and the circuit breaker has not disabled automatic recovery.

### Why Docker Restart Policy?

The restart policy provides application recovery without requiring a separate systemd service for the application container.

Docker handles the application lifecycle, while systemd manages the Docker daemon. The Python monitoring service temporarily changes the container restart policy to `no` when the circuit breaker opens, and restores `unless-stopped` after a successful recovery test.

## 10. Continuous Crash Monitoring and Circuit Breaker

Docker automatically restarting the application does not necessarily indicate that the application is healthy.

For example, an application might repeatedly crash and restart without remaining operational.

To detect and control this situation, I implemented a custom Python monitoring service with a circuit-breaker approach.

**Monitoring script:** `monitoring/check_restarts.py`

**Systemd service:** `monitoring/testpress-monitor.service`

### 10.1 Monitoring Logic

The script continuously listens to Docker events:

```bash
docker events \
  --filter container=testpress-app \
  --filter event=start \
  --filter event=die
```

It tracks the number of consecutive application crashes.

The monitoring rules are:

* Every unexpected container crash increments the failure counter.
* If the previous container run lasted at least 60 seconds, the failure sequence resets.
* If the container crashes again before 60 seconds, the failure sequence continues.
* When five consecutive failures occur, the circuit breaker opens.
* The monitor generates a warning alert in Ubuntu's local system journal.
* While the circuit is OPEN, Docker's restart policy is changed to `no` and the container is stopped.
* The monitor enforces the OPEN state if an external action attempts to start the container during the cooldown.
* After 300 seconds, the monitor attempts recovery in HALF-OPEN mode.
* During HALF-OPEN, Docker automatic restarts remain disabled while the application is observed for 60 seconds.
* If the application remains stable for 60 seconds, the circuit closes, the failure counter resets, and Docker's `unless-stopped` policy is restored.
* If the application crashes or recovery fails during HALF-OPEN, the circuit opens again and another 300-second cooldown is scheduled.

### 10.2 Circuit Breaker States

The implementation uses three states:

**CLOSED — Normal operation**

* The application runs normally.
* Docker automatically restarts the application after unexpected crashes.
* The monitor counts consecutive failures.
* Five consecutive crashes cause the circuit to open.

**OPEN — Recovery paused**

* Docker's restart policy changes to `no`.
* The application container is stopped.
* A warning alert is generated in the Ubuntu journal.
* The monitor waits for 300 seconds before attempting recovery.
* An external/manual start during this period is stopped by the monitor.

**HALF-OPEN — Recovery testing**

* After the cooldown, the monitor attempts to start the application.
* Docker automatic restarts remain disabled during the test.
* The application must remain running for 60 seconds.
* Successful recovery closes the circuit and restores `unless-stopped`.
* A crash or failed recovery reopens the circuit and starts another 300-second cooldown.

### 10.3 Systemd Service

The monitoring service is managed by systemd.

Verification command:

```bash
multipass exec cloud-init-lab -- \
  systemctl status testpress-monitor.service --no-pager
```

Observed result:

```text
Loaded: loaded (...; enabled; ...)
Active: active (running)
```

The service runs a Python process that continuously listens to Docker events.

**Result: PASS**

### 10.4 Monitoring Service Recovery

The systemd service uses:

```ini
Restart=always
RestartSec=5
```

If the monitoring process exits, systemd attempts to restart it after five seconds.

The service is also enabled to start automatically when the VM boots.

## 11. Crash Simulation and Testing

To verify the monitoring implementation, I intentionally terminated the main process inside the Docker container.

This was performed only on the disposable test virtual machine.

The application process was terminated using its host PID:

```bash
multipass exec cloud-init-lab -- sudo sh -c \
  'kill -9 $(docker inspect --format "{{.State.Pid}}" testpress-app)'
```

This simulates an unexpected application-process crash. Docker can apply its configured restart policy without explicitly stopping the container through the Docker CLI.

### 11.1 Five Consecutive Crash Test

Five application crashes were triggered, allowing Docker time to restart the application between attempts.

The monitoring state was inspected using:

```bash
multipass exec cloud-init-lab -- \
  sudo cat /var/lib/testpress-monitor/state.json
```

The monitoring logs were inspected using:

```bash
multipass exec cloud-init-lab -- \
  sudo journalctl -t testpress-monitor --no-pager -n 20
```

**Observed result:**

* The failure counter increased from 1 to 5.
* The fifth consecutive crash activated the circuit breaker.
* The state changed to `mode: open`.
* Docker's restart policy changed to `no`.
* The container status became `exited`.
* The monitor recorded an alert.

**Result: PASS**

### 11.2 Docker Recovery Pause Test

After the fifth crash, Docker was inspected:

```bash
multipass exec cloud-init-lab -- sudo docker inspect --format \
  'Status={{.State.Status}} RestartPolicy={{.HostConfig.RestartPolicy.Name}} RestartCount={{.RestartCount}}' \
  testpress-app
```

Observed result:

```text
Status=exited RestartPolicy=no RestartCount=5
```

**Result: PASS**

This confirms that the container was stopped and Docker's automatic restart policy was disabled after the failure threshold was reached.

### 11.3 Manual Start During OPEN Test

To verify that the OPEN state is enforced, I attempted to start the container manually during the cooldown:

```bash
multipass exec cloud-init-lab -- sudo docker start testpress-app
```

The monitor stopped the container again. Inspection showed:

```text
Status=exited RestartPolicy=no
```

**Result: PASS**

This confirms that the monitor enforces the OPEN state during the cooldown, including when an external/manual start is attempted.

### 11.4 Automatic Recovery and HALF-OPEN Stability Test

After the 300-second cooldown, the monitor automatically attempted recovery.

The observed monitoring logs were:

```text
09:37:20 - Fifth crash; circuit OPEN
09:42:20 - Cooldown completed; beginning recovery
09:42:21 - HALF-OPEN; testing 60-second stability
09:43:21 - Stable for 60 seconds; circuit CLOSED; automatic restarts restored
```

The container was inspected after recovery:

```text
Status=running RestartPolicy=unless-stopped
```

**Result: PASS**

This confirms that the monitor automatically started the application, observed it for 60 seconds, closed the circuit, and restored Docker's automatic restart policy.

### 11.5 Failed HALF-OPEN Recovery Test

To test failed recovery, I triggered another series of five consecutive crashes to open the circuit again.

The second cooldown and recovery attempt were recorded:

```text
09:46:14 - Fifth crash; circuit OPEN
09:51:14 - Cooldown completed; beginning recovery
09:51:14 - HALF-OPEN; testing 60-second stability
```

During the HALF-OPEN recovery window, I terminated the application process again.

The state file then showed:

```json
{
  "mode": "open",
  "failures": 5,
  "started_at": null,
  "retry_at": 1793507201.0646436,
  "retry_started_at": null,
  "last_event_ns": 1793506901062940705
}
```

**Result: PASS**

This confirms that a crash during HALF-OPEN returns the circuit breaker to OPEN and schedules another 300-second cooldown instead of permanently stopping recovery.

### 11.6 Stability Reset Test

The application was allowed to run for more than 60 seconds during the successful HALF-OPEN recovery test.

The monitoring logs confirmed:

```text
09:43:21 - Stable for 60 seconds; circuit CLOSED; automatic restarts restored
```

The state returned to:

```json
{
  "mode": "closed",
  "failures": 0,
  "retry_at": null,
  "retry_started_at": null
}
```

**Result: PASS**

This confirms that successful stable recovery resets the failure counter and restores normal operation.

**Important distinction:** The current stability condition measures container uptime, not continuous success of the HTTP health endpoint.

## 12. Reboot Recovery Test

To verify recovery after a VM restart, I executed:

```bash
multipass restart cloud-init-lab
```

Then checked the container and monitoring service:

```bash
multipass exec cloud-init-lab -- \
  sh -c 'sudo docker ps --filter name=^/testpress-app$ --format "Container: {{.Names}} | Status: {{.Status}}" && systemctl is-active testpress-monitor.service'
```

### Actual Result

```text
Container: testpress-app | Status: Up Less than a second
active
```

**Result: PASS**

This confirms that:

* The Docker container restarted after the VM reboot.
* The systemd monitoring service started automatically.

A separate post-reboot HTTP health-check result was not recorded as part of this verification.

## 13. Idempotency

Idempotency means running the same provisioning operation multiple times should not unnecessarily create duplicate resources.

The deployment uses checks before cloning the repository, building the Docker image, or creating the container.

For example:

```bash
docker image inspect testpress-app:v1 >/dev/null 2>&1 || \
  docker build -t testpress-app:v1 /opt/cloud-init-playground/app
```

If the image already exists, the build is skipped.

Similar checks are used for the repository and container.

The repeated deployment checks did not create duplicate resources during testing.

Cloud-init also normally executes its first-boot deployment modules once per instance.

**Limitation:** These existence checks do not automatically update an existing application to a newer Git commit or Docker image.

### Scope Note

FFmpeg was part of the original assignment requirements but was intentionally omitted from this implementation. It should be treated as an outstanding requirement rather than a completed feature.

## 14. Conclusion

Through this assignment, I implemented an automated Ubuntu server provisioning workflow using cloud-init and Multipass.

The implementation installs the required packages, creates an application user, configures the environment, deploys a Dockerized Python application, and enables automatic recovery after application crashes and VM reboots.

I also developed a continuous monitoring service with a circuit-breaker mechanism. It detects five consecutive application crashes, pauses Docker automatic recovery for five minutes, and then attempts recovery using a 60-second HALF-OPEN stability test. Practical testing confirmed the failure threshold, recovery pause, manual-start enforcement during cooldown, successful automatic recovery, and reopening of the circuit after a failed HALF-OPEN attempt.

This project helped me understand how infrastructure automation, containerization, Linux service management, application monitoring, and circuit-breaker-based recovery work together to create a reproducible and more reliable server deployment.

**Repository:** <https://github.com/HarishV14/cloud-init-playground>
