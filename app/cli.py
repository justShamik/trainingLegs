"""Flask CLI Commands for COROS Synchronization."""
import click
from flask import current_app
from flask.cli import AppGroup, with_appcontext
from app.data.sync import perform_sync

sync_cli = AppGroup("sync", help="COROS Data Synchronization Commands")


@click.command("races-refresh")
@click.option("--race-id", "race_ids", multiple=True, help="Only scan these race ids (repeatable)")
@click.option("--discover", is_flag=True, help="Also list unverified Delhi NCR 50K candidates")
@click.option("--verbose", "-v", is_flag=True, help="Show per-URL fetch results")
@with_appcontext
def races_refresh_command(race_ids, discover: bool, verbose: bool):
    """Scan race websites for registration-status changes and store the results."""
    from app.races.service import discover_candidates, refresh_races
    db_path = current_app.config.get("DATABASE_PATH")
    summary = refresh_races(db_path=db_path, race_ids=list(race_ids) or None)
    for r in summary["results"]:
        if r.get("skipped"):
            click.echo(f"- {r['race_id']}: skipped ({r['skipped']})")
            continue
        flag = " CHANGED" if r["changed"] else ""
        click.echo(f"- {r['race_id']}: {r['status']} ({r['confidence']}){flag}"
                   + (f" | error: {r['error']}" if r.get("error") else ""))
        if verbose:
            for p in r.get("pages", []):
                click.echo(f"    {p['url']} -> HTTP {p['http_status']} {p.get('error') or 'ok'}")
    click.secho(f"Checked {summary['checked']}, changed {summary['changed']}, errors {summary['errors']}",
                fg="red" if summary["errors"] else "green")
    if discover:
        pages = []
        cands = discover_candidates(report=pages)
        for p in pages if verbose else []:
            click.echo(f"    listing {p['url']} -> HTTP {p['http_status']} {p.get('error') or 'ok'} ({p['found']} found)")
        click.echo(f"NCR 50K candidates (unverified): {len(cands)}")
        for c in cands:
            click.echo(f"  * {c['name']} | {c['date_text']} | {c['url']}")

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
