"""Database layer for queuectl - SQLite persistence for jobs."""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path


class Database:
    """SQLite database manager for job queue."""
    
    def __init__(self, db_path: str = "queuectl.db", timeout: float = 30.0):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
            timeout: Timeout in seconds for database operations (default: 30.0)
        """
        self.db_path = db_path
        self._ensure_db_directory()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=timeout)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._create_config_table()
    
    def _ensure_db_directory(self):
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            Path(db_dir).mkdir(parents=True, exist_ok=True)
    
    def _create_tables(self):
        """Create jobs and config tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_message TEXT,
                next_retry_at TEXT
            )
        """)
        
        # Create indexes for better performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_state ON jobs(state)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_next_retry_at ON jobs(next_retry_at)
        """)
        
        self.conn.commit()
    
    def _create_config_table(self):
        """Create configuration table."""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        
        # Insert default config if not exists
        defaults = {
            'max-retries': '3',
            'backoff-base': '2',
            'workers': '1'
        }
        
        for key, value in defaults.items():
            cursor.execute("""
                INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)
            """, (key, value))
        
        self.conn.commit()
    
    def create_job(self, job_id: str, command: str, max_retries: int = 3) -> Dict[str, Any]:
        """Create a new job."""
        now = datetime.utcnow().isoformat() + 'Z'
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO jobs (id, command, state, attempts, max_retries, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (job_id, command, 'pending', 0, max_retries, now, now))
        self.conn.commit()
        return self.get_job(job_id)
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    
    def get_pending_jobs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get pending jobs ready for processing (atomically mark as processing)."""
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat() + 'Z'
        
        # Use a transaction to atomically select and update jobs
        # This prevents race conditions when multiple workers dequeue simultaneously
        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("""
                SELECT * FROM jobs 
                WHERE state = 'pending' 
                AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at ASC
                LIMIT ?
            """, (now, limit))
            jobs = [dict(row) for row in cursor.fetchall()]
            
            # Mark jobs as processing atomically
            if jobs:
                job_ids = [job['id'] for job in jobs]
                placeholders = ','.join('?' * len(job_ids))
                cursor.execute(f"""
                    UPDATE jobs 
                    SET state = 'processing', updated_at = ?
                    WHERE id IN ({placeholders})
                """, (now, *job_ids))
            
            self.conn.commit()
            return jobs
        except Exception as e:
            self.conn.rollback()
            raise
    
    def update_job_state(self, job_id: str, state: str, error_message: Optional[str] = None):
        """Update job state."""
        now = datetime.utcnow().isoformat() + 'Z'
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET state = ?, updated_at = ?, error_message = ?
            WHERE id = ?
        """, (state, now, error_message, job_id))
        self.conn.commit()
    
    def increment_attempts(self, job_id: str) -> int:
        """Increment job attempts and return new count."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET attempts = attempts + 1, updated_at = ?
            WHERE id = ?
        """, (datetime.utcnow().isoformat() + 'Z', job_id))
        self.conn.commit()
        
        job = self.get_job(job_id)
        return job['attempts'] if job else 0
    
    def set_next_retry_at(self, job_id: str, next_retry_at: str):
        """Set the next retry timestamp."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET next_retry_at = ?, updated_at = ?
            WHERE id = ?
        """, (next_retry_at, datetime.utcnow().isoformat() + 'Z', job_id))
        self.conn.commit()
    
    def move_to_dlq(self, job_id: str, error_message: str):
        """Move job to Dead Letter Queue (state: 'dead')."""
        now = datetime.utcnow().isoformat() + 'Z'
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET state = 'dead', updated_at = ?, error_message = ?, next_retry_at = NULL
            WHERE id = ?
        """, (now, error_message, job_id))
        self.conn.commit()
    
    def get_dlq_jobs(self) -> List[Dict[str, Any]]:
        """Get all jobs in Dead Letter Queue (state: 'dead' or 'dlq' for backward compatibility)."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM jobs 
            WHERE state IN ('dead', 'dlq')
            ORDER BY updated_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_all_jobs(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all jobs, optionally filtered by state."""
        cursor = self.conn.cursor()
        if state:
            cursor.execute("SELECT * FROM jobs WHERE state = ? ORDER BY created_at DESC", (state,))
        else:
            cursor.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    
    def retry_dlq_job(self, job_id: str):
        """Reset a DLQ job (dead/dlq state) for retry."""
        now = datetime.utcnow().isoformat() + 'Z'
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET state = 'pending', attempts = 0, updated_at = ?, error_message = NULL, next_retry_at = NULL
            WHERE id = ? AND state IN ('dead', 'dlq')
        """, (now, job_id))
        self.conn.commit()
    
    def reset_stuck_jobs(self, timeout_seconds: int = 3600) -> int:
        """Reset jobs stuck in 'processing' state (e.g., from crashed workers).
        
        Args:
            timeout_seconds: Reset jobs that have been processing for longer than this.
        
        Returns:
            Number of jobs reset.
        """
        from datetime import timedelta
        timeout_threshold = (datetime.utcnow() - timedelta(seconds=timeout_seconds)).isoformat() + 'Z'
        now = datetime.utcnow().isoformat() + 'Z'
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE jobs 
            SET state = 'pending', updated_at = ?, error_message = 'Job was stuck in processing state and reset'
            WHERE state = 'processing' AND updated_at < ?
        """, (now, timeout_threshold))
        count = cursor.rowcount
        self.conn.commit()
        return count
    
    def set_config(self, key: str, value: str):
        """Set configuration value."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)
        """, (key, value))
        self.conn.commit()
    
    def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get configuration value."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else default
    
    def get_all_config(self) -> Dict[str, str]:
        """Get all configuration values."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        return {row['key']: row['value'] for row in cursor.fetchall()}
    
    def close(self):
        """Close database connection."""
        self.conn.close()

