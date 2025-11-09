"""Job queue manager for queuectl."""

import uuid
from typing import Optional, Dict, Any, List
from database import Database


class JobQueue:
    """Job queue manager with retry and DLQ support."""
    
    def __init__(self, db_path: str = "queuectl.db"):
        """Initialize job queue."""
        self.db = Database(db_path)
    
    def enqueue(self, command: str, max_retries: Optional[int] = None, job_id: Optional[str] = None) -> Dict[str, Any]:
        """Enqueue a new job.
        
        Args:
            command: Command to execute
            max_retries: Maximum number of retries (default: from config)
            job_id: Optional job ID (if not provided, UUID is generated)
        """
        if max_retries is None:
            max_retries = int(self.db.get_config('max-retries', '3'))
        
        if job_id is None:
            job_id = str(uuid.uuid4())
        
        job = self.db.create_job(job_id, command, max_retries)
        return job
    
    def dequeue(self, limit: int = 1) -> List[Dict[str, Any]]:
        """Dequeue pending jobs."""
        return self.db.get_pending_jobs(limit)
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        return self.db.get_job(job_id)
    
    def mark_processing(self, job_id: str):
        """Mark job as processing."""
        self.db.update_job_state(job_id, 'processing')
    
    def mark_completed(self, job_id: str):
        """Mark job as completed."""
        self.db.update_job_state(job_id, 'completed')
    
    def mark_failed(self, job_id: str, error_message: str, backoff_base: float = 2.0):
        """Mark job as failed and schedule retry or move to DLQ."""
        attempts = self.db.increment_attempts(job_id)
        job = self.db.get_job(job_id)
        
        if not job:
            return
        
        max_retries = job['max_retries']
        
        if attempts >= max_retries:
            # Move to DLQ
            self.db.move_to_dlq(job_id, error_message)
        else:
            # Schedule retry with exponential backoff
            from datetime import datetime, timedelta
            delay = backoff_base ** attempts
            next_retry_at = (datetime.utcnow() + timedelta(seconds=delay)).isoformat() + 'Z'
            self.db.set_next_retry_at(job_id, next_retry_at)
            self.db.update_job_state(job_id, 'pending', error_message)
    
    def get_dlq_jobs(self) -> List[Dict[str, Any]]:
        """Get all DLQ jobs."""
        return self.db.get_dlq_jobs()
    
    def retry_dlq_job(self, job_id: str):
        """Retry a DLQ job."""
        self.db.retry_dlq_job(job_id)
    
    def get_all_jobs(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all jobs, optionally filtered by state."""
        return self.db.get_all_jobs(state)
    
    def reset_stuck_jobs(self, timeout_seconds: int = 3600) -> int:
        """Reset jobs stuck in processing state."""
        return self.db.reset_stuck_jobs(timeout_seconds)
    
    def close(self):
        """Close database connection."""
        self.db.close()

