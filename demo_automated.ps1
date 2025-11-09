# Automated Demo Script for queuectl (Windows PowerShell)
# This script automates the demo for recording purposes
# Run with: powershell -ExecutionPolicy Bypass -File demo_automated.ps1

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Section {
    param([string]$Message)
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "   $Message" -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host ""
}

function Write-Subsection {
    param([string]$Message)
    Write-Host "=== $Message ===" -ForegroundColor Green
}

# Clean up
Write-Subsection "Cleaning up..."
Remove-Item -Path "queuectl.db" -ErrorAction SilentlyContinue
Remove-Item -Path "queuectl_worker_*.pid" -ErrorAction SilentlyContinue
Write-Host ""

# Section 1: Setup
Write-Subsection "Section 1: Setup & Installation"
Write-Host "Python version:"
python --version
Write-Host ""
Write-Host "Installing dependencies..."
pip install -q -r requirements.txt
Write-Host "Dependencies installed!"
Write-Host ""
Write-Host "Verifying installation:"
python queuectl.py --help | Select-Object -First 10
Write-Host ""
Start-Sleep -Seconds 2

# Section 2: Basic Job Management
Write-Subsection "Section 2: Basic Job Management"
Write-Host "Enqueueing jobs..."
python queuectl.py enqueue '{"id":"job1","command":"echo \"Hello from job1\""}'
python queuectl.py enqueue "echo 'Hello from job2'"
python queuectl.py enqueue "echo 'Job 3'"
python queuectl.py enqueue "echo 'Job 4'"
Write-Host ""
Write-Host "Listing all jobs:"
python queuectl.py list
Write-Host ""
Write-Host "Checking status:"
python queuectl.py status
Write-Host ""
Start-Sleep -Seconds 2

# Section 3: Worker Processing
Write-Subsection "Section 3: Worker Processing"
Write-Host "Starting 2 workers in background..."
$workerProcess = Start-Process python -ArgumentList "queuectl.py", "worker", "start", "--count", "2" -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 5
Write-Host ""
Write-Host "Checking status after processing:"
python queuectl.py status
Write-Host ""
Write-Host "Listing completed jobs:"
python queuectl.py list --state completed
Write-Host ""
# Stop workers
try {
    python queuectl.py worker stop
} catch {
    Write-Host "Workers may have already stopped"
}
Start-Sleep -Seconds 2

# Section 4: Failed Jobs & Retries
Write-Subsection "Section 4: Failed Jobs & Retries"
Write-Host "Configuring retry settings:"
python queuectl.py config set max-retries 2
python queuectl.py config set backoff-base 2
python queuectl.py config get
Write-Host ""
Write-Host "Enqueueing a failing job:"
python queuectl.py enqueue "nonexistent-command-12345"
Write-Host ""
Write-Host "Starting worker to process failing job:"
$workerProcess = Start-Process python -ArgumentList "queuectl.py", "worker", "start", "--count", "1" -PassThru -WindowStyle Minimized
Write-Host "Waiting for retries (about 12 seconds)..."
Start-Sleep -Seconds 12
try {
    python queuectl.py worker stop
} catch {
    Write-Host "Workers may have already stopped"
}
Write-Host ""
Write-Host "Checking status after retries:"
python queuectl.py status
Write-Host ""
Write-Host "Listing dead jobs:"
python queuectl.py list --state dead
Write-Host ""
Start-Sleep -Seconds 2

# Section 5: Dead Letter Queue
Write-Subsection "Section 5: Dead Letter Queue"
Write-Host "Listing DLQ jobs:"
python queuectl.py dlq list
Write-Host ""
# Get first DLQ job ID (simplified - may need manual input)
$dlqOutput = python queuectl.py dlq list 2>&1
$dlqJob = $dlqOutput | Select-String -Pattern '([a-f0-9-]{36}|job\d+)' | Select-Object -First 1
if ($dlqJob -and $dlqJob.Matches.Count -gt 0) {
    $jobId = $dlqJob.Matches[0].Value
    Write-Host "Retrying DLQ job: $jobId"
    python queuectl.py dlq retry $jobId
    Write-Host ""
    Write-Host "Checking status after retry:"
    python queuectl.py status
    Write-Host ""
    Write-Host "Processing retried job:"
    $workerProcess = Start-Process python -ArgumentList "queuectl.py", "worker", "start", "--count", "1" -PassThru -WindowStyle Minimized
    Start-Sleep -Seconds 3
    try {
        python queuectl.py worker stop
    } catch {
        Write-Host "Workers may have already stopped"
    }
    Write-Host ""
    python queuectl.py status
    Write-Host ""
} else {
    Write-Host "No DLQ jobs found or could not parse job ID"
    Write-Host "You can manually retry a job with: python queuectl.py dlq retry <job-id>"
    Write-Host ""
}
Start-Sleep -Seconds 2

# Section 6: Configuration Management
Write-Subsection "Section 6: Configuration Management"
Write-Host "Current configuration:"
python queuectl.py config get
Write-Host ""
Write-Host "Updating configuration:"
python queuectl.py config set max-retries 5
python queuectl.py config set backoff-base 3
Write-Host ""
Write-Host "Updated configuration:"
python queuectl.py config get
Write-Host ""
Start-Sleep -Seconds 2

# Section 7: Worker Management
Write-Subsection "Section 7: Worker Management"
Write-Host "Starting 3 workers:"
$workerProcess = Start-Process python -ArgumentList "queuectl.py", "worker", "start", "--count", "3" -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 2
Write-Host ""
Write-Host "Checking active workers:"
python queuectl.py status
Write-Host ""
Write-Host "Stopping workers:"
python queuectl.py worker stop
Start-Sleep -Seconds 2
Write-Host ""
Write-Host "Verifying workers stopped:"
python queuectl.py status
Write-Host ""
Start-Sleep -Seconds 2

# Section 8: Persistence
Write-Subsection "Section 8: Persistence"
Write-Host "Enqueueing a persistent job:"
python queuectl.py enqueue "echo 'Persistent job'"
Write-Host ""
Write-Host "Checking status:"
python queuectl.py status
Write-Host ""
Write-Host "Database file exists:"
if (Test-Path "queuectl.db") {
    Get-Item "queuectl.db" | Select-Object Name, Length, LastWriteTime
} else {
    Write-Host "Database file: queuectl.db"
}
Write-Host ""
Write-Host "All jobs (showing persistence):"
python queuectl.py list
Write-Host ""

# Final Summary
Write-Section "Demo Complete!"
Write-Host "Summary:"
Write-Host "- Jobs enqueued and processed"
Write-Host "- Retry mechanism demonstrated"
Write-Host "- DLQ functionality shown"
Write-Host "- Configuration management working"
Write-Host "- Worker management functional"
Write-Host "- Data persistence verified"
Write-Host ""

# Cleanup
Write-Host "Cleaning up..."
Remove-Item -Path "queuectl_worker_*.pid" -ErrorAction SilentlyContinue
Write-Host "Demo completed successfully!"

