#!/usr/bin/env python3
"""queuectl - CLI tool for managing background job queue."""

import click
import uuid
from datetime import datetime
from tabulate import tabulate
from queue import JobQueue
from worker import start_workers
from database import Database


@click.group()
@click.option('--db-path', default='queuectl.db', help='Path to SQLite database')
@click.pass_context
def cli(ctx, db_path):
    """queuectl - Production-grade background job queue system."""
    ctx.ensure_object(dict)
    ctx.obj['db_path'] = db_path


@cli.command()
@click.argument('job_spec', required=False)
@click.option('--max-retries', type=int, help='Maximum number of retries')
@click.pass_context
def enqueue(ctx, job_spec, max_retries):
    """Enqueue a new job.
    
    Accepts either JSON format: '{"id":"job1","command":"sleep 2"}'
    or simple command string: "echo hello"
    """
    import json
    
    queue = JobQueue(ctx.obj['db_path'])
    try:
        job_id = None
        command = None
        
        if job_spec:
            # Try to parse as JSON first
            try:
                job_data = json.loads(job_spec)
                if isinstance(job_data, dict):
                    command = job_data.get('command')
                    job_id = job_data.get('id')
                    if not command:
                        click.echo("Error: JSON must contain 'command' field", err=True)
                        return
                    # Override max_retries if provided in JSON
                    if 'max_retries' in job_data and max_retries is None:
                        max_retries = job_data.get('max_retries')
                else:
                    # Not a dict, treat as command string
                    command = job_spec
            except (json.JSONDecodeError, ValueError):
                # Not JSON, treat as command string
                command = job_spec
        
        if not command:
            click.echo("Error: No command provided", err=True)
            click.echo("Usage: queuectl enqueue '{\"id\":\"job1\",\"command\":\"sleep 2\"}'")
            click.echo("   or: queuectl enqueue \"echo hello\"")
            return
        
        job = queue.enqueue(command, max_retries, job_id)
        click.echo(f"Job enqueued: {job['id']}")
        click.echo(f"Command: {command}")
        click.echo(f"Max retries: {job['max_retries']}")
    finally:
        queue.close()


@cli.group()
def worker():
    """Manage worker processes."""
    pass


@worker.command('start')
@click.option('--count', type=int, default=1, help='Number of worker processes')
@click.option('--poll-interval', type=float, default=1.0, help='Polling interval in seconds')
@click.pass_context
def worker_start(ctx, count, poll_interval):
    """Start worker processes to process jobs."""
    db_path = ctx.obj['db_path']
    click.echo(f"Starting {count} worker(s)...")
    start_workers(num_workers=count, db_path=db_path, poll_interval=poll_interval)


@worker.command('stop')
@click.pass_context
def worker_stop(ctx):
    """Stop running workers gracefully."""
    import os
    import signal
    import glob
    
    # Look for PID files
    pid_files = glob.glob('queuectl_worker_*.pid')
    
    if not pid_files:
        click.echo("No running workers found.")
        return
    
    stopped = 0
    for pid_file in pid_files:
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if process is still running
            try:
                os.kill(pid, 0)  # Check if process exists
                os.kill(pid, signal.SIGTERM)  # Send termination signal
                click.echo(f"Sent termination signal to worker process {pid}")
                stopped += 1
                # Remove PID file
                os.remove(pid_file)
            except ProcessLookupError:
                click.echo(f"Worker process {pid} not found (already stopped)")
                os.remove(pid_file)
            except PermissionError:
                click.echo(f"Permission denied: Cannot stop worker process {pid}")
        except (ValueError, FileNotFoundError) as e:
            click.echo(f"Error reading PID file {pid_file}: {e}")
            try:
                os.remove(pid_file)
            except:
                pass
    
    if stopped > 0:
        click.echo(f"Stopped {stopped} worker(s)")
    else:
        click.echo("No workers were stopped.")


@cli.command()
@click.pass_context
def status(ctx):
    """Show summary of all job states & active workers."""
    import os
    import glob
    
    queue = JobQueue(ctx.obj['db_path'])
    try:
        # Count jobs by state
        all_jobs = queue.get_all_jobs()
        states = {}
        for job in all_jobs:
            state = job['state']
            states[state] = states.get(state, 0) + 1
        
        # Show job summary
        click.echo("\n=== Job Status Summary ===")
        if states:
            table_data = [[state, count] for state, count in sorted(states.items())]
            click.echo(tabulate(table_data, headers=['State', 'Count'], tablefmt='grid'))
        else:
            click.echo("No jobs found.")
        
        # Show active workers
        click.echo("\n=== Active Workers ===")
        pid_files = glob.glob('queuectl_worker_*.pid')
        active_workers = []
        for pid_file in pid_files:
            try:
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                # Check if process is still running
                try:
                    os.kill(pid, 0)  # Check if process exists
                    active_workers.append(pid)
                except ProcessLookupError:
                    # Process not found, remove stale PID file
                    try:
                        os.remove(pid_file)
                    except:
                        pass
            except (ValueError, FileNotFoundError):
                pass
        
        if active_workers:
            click.echo(f"Active workers: {len(active_workers)}")
            for pid in active_workers:
                click.echo(f"  - Worker PID: {pid}")
        else:
            click.echo("No active workers.")
        click.echo()
    finally:
        queue.close()


@cli.command('list')
@click.option('--state', type=click.Choice(['pending', 'processing', 'completed', 'failed', 'dlq', 'dead']), 
              help='Filter jobs by state')
@click.pass_context
def list_jobs(ctx, state):
    """List jobs by state."""
    queue = JobQueue(ctx.obj['db_path'])
    try:
        # Query for 'dead' state (which is what DLQ jobs use)
        # Also support 'dlq' for backward compatibility
        if state == 'dead' or state == 'dlq':
            # Get both 'dead' and 'dlq' jobs for compatibility
            all_jobs = queue.get_all_jobs()
            jobs = [job for job in all_jobs if job['state'] in ('dead', 'dlq')]
        else:
            jobs = queue.get_all_jobs(state)
        
        if jobs:
            _print_jobs_table(jobs)
        else:
            click.echo("No jobs found.")
    finally:
        queue.close()


@cli.group()
def dlq():
    """Manage Dead Letter Queue."""
    pass


@dlq.command('list')
@click.pass_context
def dlq_list(ctx):
    """List jobs in Dead Letter Queue."""
    queue = JobQueue(ctx.obj['db_path'])
    try:
        dlq_jobs = queue.get_dlq_jobs()
        if dlq_jobs:
            _print_jobs_table(dlq_jobs)
        else:
            click.echo("Dead Letter Queue is empty.")
    finally:
        queue.close()


@dlq.command('retry')
@click.argument('job_id')
@click.pass_context
def dlq_retry(ctx, job_id):
    """Retry a DLQ job."""
    queue = JobQueue(ctx.obj['db_path'])
    try:
        job = queue.get_job(job_id)
        if job and job['state'] in ('dlq', 'dead'):
            queue.retry_dlq_job(job_id)
            click.echo(f"Job {job_id} moved back to pending queue")
        else:
            click.echo(f"Job not found in DLQ: {job_id}")
    finally:
        queue.close()


@cli.group()
def config():
    """Manage configuration."""
    pass


@config.command('set')
@click.argument('key')
@click.argument('value')
@click.pass_context
def config_set(ctx, key, value):
    """Set a configuration value."""
    db = Database(ctx.obj['db_path'])
    try:
        db.set_config(key, value)
        click.echo(f"Configuration updated: {key} = {value}")
    finally:
        db.close()


@config.command('get')
@click.option('--key', help='Get specific config key')
@click.pass_context
def config_get(ctx, key):
    """Get configuration value(s)."""
    db = Database(ctx.obj['db_path'])
    try:
        if key:
            value = db.get_config(key)
            if value:
                click.echo(f"{key} = {value}")
            else:
                click.echo(f"Configuration key not found: {key}")
        else:
            configs = db.get_all_config()
            if configs:
                table = [[k, v] for k, v in configs.items()]
                click.echo(tabulate(table, headers=['Key', 'Value'], tablefmt='grid'))
            else:
                click.echo("No configuration found.")
    finally:
        db.close()


def _print_jobs_table(jobs):
    """Print jobs in a table format."""
    table_data = []
    for job in jobs:
        table_data.append([
            job['id'][:8] + '...',
            job['command'][:50] + ('...' if len(job['command']) > 50 else ''),
            job['state'],
            job['attempts'],
            job['max_retries'],
            _format_datetime(job['created_at']),
            _format_datetime(job['updated_at'])
        ])
    
    headers = ['ID', 'Command', 'State', 'Attempts', 'Max Retries', 'Created', 'Updated']
    click.echo(tabulate(table_data, headers=headers, tablefmt='grid'))


def _print_job_details(job):
    """Print detailed job information."""
    click.echo(f"\nJob ID: {job['id']}")
    click.echo(f"Command: {job['command']}")
    click.echo(f"State: {job['state']}")
    click.echo(f"Attempts: {job['attempts']}/{job['max_retries']}")
    click.echo(f"Created: {_format_datetime(job['created_at'])}")
    click.echo(f"Updated: {_format_datetime(job['updated_at'])}")
    if job.get('error_message'):
        click.echo(f"Error: {job['error_message']}")
    if job.get('next_retry_at'):
        click.echo(f"Next retry: {_format_datetime(job['next_retry_at'])}")


def _format_datetime(dt_str):
    """Format ISO datetime string for display."""
    if not dt_str:
        return 'N/A'
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return dt_str


if __name__ == '__main__':
    cli()

