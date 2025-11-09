"""Worker process for processing jobs."""

import subprocess
import signal
import sys
import time
from typing import Optional, Tuple
from queue import JobQueue


class Worker:
    """Worker for processing jobs from the queue."""
    
    def __init__(self, db_path: str = "queuectl.db", worker_id: int = 0):
        """Initialize worker."""
        self.queue = JobQueue(db_path)
        self.worker_id = worker_id
        self.running = False
        self.current_job: Optional[dict] = None
        self.shutdown_requested = False
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"\n[Worker {self.worker_id}] Shutdown requested. Finishing current job...")
        self.shutdown_requested = True
        if not self.current_job:
            sys.exit(0)
    
    def _calculate_backoff_base(self) -> float:
        """Get backoff base from config."""
        return float(self.queue.db.get_config('backoff-base', '2.0'))
    
    def _execute_command(self, command: str) -> Tuple[bool, str]:
        """Execute a shell command and return success status and output."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
                check=True
            )
            return True, result.stdout
        except subprocess.TimeoutExpired:
            return False, "Command execution timeout (1 hour)"
        except subprocess.CalledProcessError as e:
            return False, f"Command failed with exit code {e.returncode}: {e.stderr}"
        except Exception as e:
            return False, f"Error executing command: {str(e)}"
    
    def process_job(self, job: dict) -> bool:
        """Process a single job."""
        job_id = job['id']
        command = job['command']
        
        print(f"[Worker {self.worker_id}] Processing job {job_id}: {command}")
        
        # Job is already marked as 'processing' during dequeue (atomic operation)
        # Execute command
        success, output = self._execute_command(command)
        
        if success:
            print(f"[Worker {self.worker_id}] Job {job_id} completed successfully")
            self.queue.mark_completed(job_id)
            return True
        else:
            print(f"[Worker {self.worker_id}] Job {job_id} failed: {output}")
            backoff_base = self._calculate_backoff_base()
            self.queue.mark_failed(job_id, output, backoff_base)
            return False
    
    def run(self, poll_interval: float = 1.0):
        """Run worker loop."""
        self.running = True
        print(f"[Worker {self.worker_id}] Started")
        
        while self.running:
            # Check for shutdown before getting new jobs
            if self.shutdown_requested:
                if self.current_job:
                    # Finish current job before shutting down
                    print(f"[Worker {self.worker_id}] Finishing current job before shutdown...")
                    self.process_job(self.current_job)
                    self.current_job = None
                print(f"[Worker {self.worker_id}] Shutting down...")
                break
            
            # Try to get a job
            jobs = self.queue.dequeue(limit=1)
            
            if jobs:
                self.current_job = jobs[0]
                self.process_job(self.current_job)
                self.current_job = None
            else:
                # No jobs available, wait before polling again
                time.sleep(poll_interval)
        
        print(f"[Worker {self.worker_id}] Stopped")
        self.queue.close()


def worker_process(worker_id: int, db_path: str, poll_interval: float):
    """Worker process entry point (module-level function for multiprocessing)."""
    import os
    
    # Write PID file for worker management
    pid_file = f'queuectl_worker_{worker_id}.pid'
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"[Worker {worker_id}] Warning: Could not write PID file: {e}")
    
    try:
        worker = Worker(db_path, worker_id)
        worker.run(poll_interval)
    finally:
        # Clean up PID file on exit
        try:
            if os.path.exists(pid_file):
                os.remove(pid_file)
        except:
            pass


def start_workers(num_workers: int = 1, db_path: str = "queuectl.db", poll_interval: float = 1.0):
    """Start multiple worker processes."""
    import multiprocessing
    import atexit
    
    # Use 'spawn' method for better cross-platform compatibility
    if hasattr(multiprocessing, 'set_start_method'):
        try:
            multiprocessing.set_start_method('spawn', force=True)
        except RuntimeError:
            pass  # Start method already set
    
    processes = []
    
    def cleanup():
        """Cleanup function to terminate all workers gracefully."""
        if processes:
            print("\nShutting down workers...")
            # First, try graceful termination (SIGTERM)
            for p in processes:
                if p.is_alive():
                    p.terminate()
            # Wait for processes to finish
            for p in processes:
                p.join(timeout=5)
            # Force kill if still alive
            for p in processes:
                if p.is_alive():
                    print(f"Force killing worker process {p.pid}")
                    p.kill()
                    p.join()
    
    atexit.register(cleanup)
    
    # Start all worker processes
    for i in range(num_workers):
        p = multiprocessing.Process(target=worker_process, args=(i, db_path, poll_interval))
        p.start()
        processes.append(p)
        print(f"Started worker {i} (PID: {p.pid})")
    
    try:
        # Wait for all processes
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        cleanup()
        sys.exit(0)

