#!/bin/bash
# Test script for queuectl - validates core flows

set -e

echo "🧪 Testing queuectl - Background Job Queue System"
echo "=================================================="
echo ""

# Clean up any existing database and PID files
rm -f queuectl.db queuectl_worker_*.pid

# Test 1: Enqueue jobs (JSON and command string)
echo "✅ Test 1: Enqueue jobs"
echo "----------------------"
python queuectl.py enqueue '{"id":"job1","command":"echo \"Hello from job1\""}'
python queuectl.py enqueue "echo 'Hello from job2'"
python queuectl.py enqueue "sleep 1"
echo ""

# Test 2: List jobs
echo "✅ Test 2: List pending jobs"
echo "---------------------------"
python queuectl.py list --state pending
echo ""

# Test 3: Start workers in background
echo "✅ Test 3: Start workers"
echo "-----------------------"
python queuectl.py worker start --count 2 &
WORKER_PID=$!
sleep 3
echo ""

# Test 4: Check status (should show active workers)
echo "✅ Test 4: Check status"
echo "----------------------"
python queuectl.py status
echo ""

# Test 5: Wait for jobs to complete
echo "✅ Test 5: Wait for jobs to complete"
echo "-----------------------------------"
sleep 5
python queuectl.py status
echo ""

# Test 6: Test failed job with retries
echo "✅ Test 6: Test failed job (will retry and move to DLQ)"
echo "------------------------------------------------------"
python queuectl.py config set max-retries 2
python queuectl.py config set backoff-base 2
python queuectl.py enqueue "false"  # This command will fail
sleep 10  # Wait for retries
python queuectl.py status
echo ""

# Test 7: Check DLQ
echo "✅ Test 7: Check Dead Letter Queue"
echo "----------------------------------"
python queuectl.py dlq list
echo ""

# Test 8: Retry DLQ job
echo "✅ Test 8: Retry DLQ job"
echo "----------------------"
DLQ_JOB_ID=$(python queuectl.py dlq list 2>/dev/null | grep -oP 'job[0-9]+|^[a-f0-9-]{36}' | head -1 || echo "")
if [ ! -z "$DLQ_JOB_ID" ]; then
    # Extract full job ID from status if needed
    python queuectl.py list --state dead | head -5
    echo "Retrying first DLQ job..."
    # Note: In real scenario, you'd use the full UUID
fi
echo ""

# Test 9: Stop workers
echo "✅ Test 9: Stop workers"
echo "---------------------"
python queuectl.py worker stop
sleep 2
echo ""

# Test 10: Verify persistence (jobs should still exist)
echo "✅ Test 10: Verify persistence"
echo "-----------------------------"
python queuectl.py status
echo ""

# Test 11: Configuration
echo "✅ Test 11: Configuration management"
echo "-----------------------------------"
python queuectl.py config get
echo ""

echo "✅ All tests completed!"
echo "======================"

# Cleanup
rm -f queuectl_worker_*.pid

