"""Flask CLI Commands for COROS Synchronization."""
import click
from flask.cli import AppGroup
from app.data.sync import perform_sync

sync_cli = AppGroup("sync", help="COROS Data Synchronization Commands")

@sync_cli.command("run")
@click.option("--full", "is_full", is_flag=True, help="Perform full historical synchronization")
@click.option("--incremental", "is_incremental", is_flag=True, help="Perform incremental sync since last timestamp")
def sync_command(is_full: bool, is_incremental: bool):
    """Run data synchronization with COROS MCP server."""
    full_sync = is_full or not is_incremental
    click.echo(f"Starting {'FULL' if full_sync else 'INCREMENTAL'} COROS data sync...")
    
    success, count, msg, duration = perform_sync(full=full_sync)
    if success:
        click.secho(f"Success: {msg}", fg="green")
    else:
        click.secho(f"Error: {msg}", fg="red")
