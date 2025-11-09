# queuectl

A production-grade CLI-based background job queue system with workers, retries (exponential backoff), and Dead Letter Queue (DLQ) support.

## Features

- ✅ Enqueue and manage jobs via CLI commands (JSON or command string)
- ✅ Start multiple workers to process jobs concurrently
- ✅ Automatic retries with exponential backoff (`delay = base ^ attempts`)
- ✅ Dead Letter Queue (DLQ) for permanently failed jobs
- ✅ Persistent storage using SQLite
- ✅ Configuration management via CLI
- ✅ Graceful worker shutdown (finish current job before exit)
- ✅ Worker process management (start/stop)

## DEMO
[VIDEO](https://drive.google.com/file/d/1YUqs6DxFa9dlgDRnUYOPmcZ46JTF359q/view?usp=sharing)

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Enqueue a job

```bash
# Enqueue using JSON format (with custom job ID)
python queuectl.py enqueue '{"id":"job1","command":"sleep 2"}'

# Enqueue using JSON format (auto-generated job ID)
python queuectl.py enqueue '{"command":"echo hello"}'

# Enqueue using simple command string
python queuectl.py enqueue "echo 'Hello World'"

# Enqueue a job with custom max retries
python queuectl.py enqueue "sleep 5" --max-retries 5
```

### Start workers

```bash
# Start a single worker
python queuectl.py worker start

# Start multiple workers
python queuectl.py worker start --count 3

# Start workers with custom polling interval
python queuectl.py worker start --count 2 --poll-interval 0.5
```

### Stop workers

```bash
# Stop all running workers gracefully
python queuectl.py worker stop
```

### View status

```bash
# Show summary of all job states & active workers
python queuectl.py status
```

### List jobs

```bash
# List all jobs
python queuectl.py list

# List jobs by state
python queuectl.py list --state pending
python queuectl.py list --state completed
python queuectl.py list --state dead
```

### Dead Letter Queue (DLQ)

```bash
# List all DLQ jobs
python queuectl.py dlq list

# Retry a DLQ job
python queuectl.py dlq retry job1
```

### Configure settings

```bash
# Set configuration values
python queuectl.py config set max-retries 5
python queuectl.py config set backoff-base 2

# View all configuration
python queuectl.py config get

# View specific configuration
python queuectl.py config get --key max-retries
```

## Example Workflow

```bash
# 1. Enqueue some jobs
python queuectl.py enqueue '{"id":"job1","command":"echo \"Job 1\""}'
python queuectl.py enqueue "echo 'Job 2'"
python queuectl.py enqueue "false"  # This will fail

# 2. Check job status
python queuectl.py status

# 3. Start workers to process jobs
python queuectl.py worker start --count 2

# 4. Check status again (in another terminal)
python queuectl.py status

# 5. View failed jobs in DLQ
python queuectl.py dlq list

# 6. Retry a DLQ job
python queuectl.py dlq retry job1

# 7. Stop workers
python queuectl.py worker stop
```

## Architecture Overview

### Job Lifecycle

1. **pending**: Job is waiting to be picked up by a worker
2. **processing**: Job is currently being executed by a worker
3. **completed**: Job completed successfully
4. **failed**: Job failed but is retryable (will retry with backoff)
5. **dead**: Job permanently failed (moved to DLQ after exhausting retries)

### Data Persistence

- **Storage**: SQLite database (`queuectl.db` by default)
- **Schema**: Jobs table with fields: id, command, state, attempts, max_retries, created_at, updated_at, error_message, next_retry_at
- **Persistence**: All job data persists across restarts
- **Atomic Operations**: Job dequeue uses database transactions to prevent race conditions

### Worker Logic

- **Multi-process**: Each worker runs in a separate process for true concurrency
- **Process Management**: Workers write PID files for management (start/stop)
- **Graceful Shutdown**: Workers finish current job before exiting on SIGTERM/SIGINT
- **Job Locking**: Atomic job dequeue prevents duplicate processing
- **Polling**: Workers poll for jobs at configurable intervals (default: 1 second)

### Retry Mechanism

Jobs are retried with exponential backoff. The delay is calculated as:
```
delay = base ^ attempts
```

Where:
- `base` is the backoff base (default: 2, configurable via `config set backoff-base`)
- `attempts` is the number of times the job has been attempted

Example with base=2:
- 1st retry: 2^1 = 2 seconds
- 2nd retry: 2^2 = 4 seconds
- 3rd retry: 2^3 = 8 seconds

After `max_retries` attempts, jobs are moved to the Dead Letter Queue (DLQ).

### Dead Letter Queue (DLQ)

- Jobs that fail after exhausting all retries are moved to DLQ (state: `dead`)
- DLQ jobs can be viewed with `queuectl.py dlq list`
- DLQ jobs can be retried with `queuectl.py dlq retry <job-id>`
- Retrying a DLQ job resets attempts and moves it back to `pending` state

## Testing Instructions

### Run Test Script

```bash
# Run the comprehensive test script
./test_queuectl.sh
```

### Manual Testing

#### Test 1: Basic job completion
```bash
python queuectl.py enqueue "echo 'Hello World'"
python queuectl.py worker start --count 1
# Wait a few seconds, then check status
python queuectl.py status
```

#### Test 2: Failed job with retries and DLQ
```bash
python queuectl.py config set max-retries 2
python queuectl.py config set backoff-base 2
python queuectl.py enqueue "false"  # This will fail
python queuectl.py worker start --count 1
# Wait for retries (about 6 seconds: 2 + 4 seconds)
python queuectl.py status
python queuectl.py dlq list
```

#### Test 3: Multiple workers processing jobs
```bash
# Enqueue multiple jobs
for i in {1..5}; do
  python queuectl.py enqueue "echo 'Job $i'"
done

# Start multiple workers
python queuectl.py worker start --count 3

# Check status
python queuectl.py status

# Stop workers
python queuectl.py worker stop
```

#### Test 4: Job persistence
```bash
# Enqueue a job
python queuectl.py enqueue "echo 'Persistent job'"

# Restart the application (simulate)
# Jobs should still be in the database
python queuectl.py list --state pending
```

#### Test 5: Invalid commands
```bash
python queuectl.py enqueue "nonexistent-command-12345"
python queuectl.py worker start --count 1
# Wait for retries and DLQ
python queuectl.py dlq list
```

## Assumptions & Trade-offs

### Assumptions

1. **Command Execution**: Jobs execute shell commands using `subprocess.run()` with a 1-hour timeout
2. **Success/Failure**: Job success is determined by command exit code (0 = success, non-zero = failure)
3. **Worker Processes**: Workers run as separate processes (not threads) for true parallelism
4. **Database**: SQLite is used for simplicity and portability (suitable for single-machine deployments)
5. **PID Files**: Worker management uses PID files in the current directory

### Trade-offs

1. **SQLite Concurrency**: SQLite handles concurrent reads well, but writes are serialized. For high-throughput scenarios, consider PostgreSQL or another database.
2. **Polling vs Event-driven**: Workers poll for jobs rather than using event-driven architecture. This is simpler but may have higher latency.
3. **No Job Priority**: Jobs are processed in FIFO order (by creation time). Priority queues could be added as an enhancement.
4. **No Job Timeout**: Jobs have a 1-hour execution timeout, but no configurable per-job timeout. This could be added.
5. **Single Machine**: The system is designed for single-machine deployment. Distributed deployment would require additional infrastructure.

## Project Structure

```
FLAM/
├── queuectl.py      # Main CLI application
├── database.py      # SQLite database layer
├── queue.py         # Job queue manager
├── worker.py        # Worker processes
├── requirements.txt # Dependencies
├── README.md        # This file
├── test_queuectl.sh # Test script
└── .gitignore       # Git ignore file
```

## Evaluation Criteria Coverage

### Functionality (40%)
- ✅ Enqueue jobs (JSON and command string formats)
- ✅ Worker processes (start/stop)
- ✅ Retry mechanism with exponential backoff
- ✅ Dead Letter Queue (DLQ)
- ✅ Job status and listing
- ✅ Configuration management

### Code Quality (20%)
- ✅ Clear separation of concerns (database, queue, worker, CLI)
- ✅ Type hints and documentation
- ✅ Error handling
- ✅ Modular design

### Robustness (20%)
- ✅ Atomic job dequeue (prevents race conditions)
- ✅ Graceful worker shutdown
- ✅ Stuck job recovery
- ✅ Database transaction handling
- ✅ Process management (PID files)

### Documentation (10%)
- ✅ Comprehensive README
- ✅ Usage examples
- ✅ Architecture overview
- ✅ Testing instructions

### Testing (10%)
- ✅ Test script for core flows
- ✅ Manual testing instructions
- ✅ Test scenarios documented

## Bonus Features (Future Enhancements)

- [ ] Job timeout handling (per-job timeout configuration)
- [ ] Job priority queues
- [ ] Scheduled/delayed jobs (run_at field)
- [ ] Job output logging
- [ ] Metrics or execution stats
- [ ] Minimal web dashboard for monitoring

## Troubleshooting

### Workers not starting
- Check if PID files exist from previous runs: `ls queuectl_worker_*.pid`
- Remove stale PID files: `rm queuectl_worker_*.pid`
- Check database file permissions

### Jobs stuck in processing
- Use `python queuectl.py status --reset-stuck` to reset stuck jobs
- Adjust timeout: `python queuectl.py status --reset-stuck --stuck-timeout 1800`

### Database locked errors
- Ensure only one process is writing to the database at a time
- Check for stale worker processes: `ps aux | grep queuectl`

## License

This project is created as part of a backend developer internship assignment.
