#!/usr/bin/env python3
import logging
import click
from pathlib import Path
import json

from config import get_config
from migrator import SlackMigrator

def setup_logging(log_level: str):
    """Setup logging configuration"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('slack_migrator.log'),
            logging.StreamHandler()
        ]
    )

@click.group()
@click.option('--log-level', default='INFO', help='Logging level (DEBUG, INFO, WARNING, ERROR)')
@click.pass_context
def cli(ctx, log_level):
    """Slack Workspace Migrator - Download and upload Slack workspace data"""
    ctx.ensure_object(dict)
    setup_logging(log_level)

    try:
        config = get_config()
        ctx.obj['config'] = config
        ctx.obj['migrator'] = SlackMigrator(config)
    except Exception as e:
        click.echo(f"Error loading configuration: {e}")
        click.echo("Please check your .env file and ensure all required tokens are set.")
        ctx.exit(1)

@cli.command()
@click.option('--channel', help='Download only a specific channel (by name)')
@click.option('--force', is_flag=True, help='Force re-download even if cached data exists')
@click.pass_context
def download(ctx, channel, force):
    """Download data from source Slack workspace"""
    migrator = ctx.obj['migrator']

    if channel:
        click.echo(f"Starting download of channel #{channel} from source workspace...")
        try:
            data = migrator.download_single_channel(channel, force=force)
            if data:
                from_cache = data.get('from_cache', False)
                status_icon = "📁" if from_cache else "✅"
                source_text = "from cache" if from_cache else "downloaded"

                click.echo(f"{status_icon} Channel #{channel} data {source_text}!")
                click.echo(f"   - Channel: #{channel}")
                click.echo(f"   - Messages: {len(data.get('messages', []))}")
                click.echo(f"   - Files: {data.get('file_count', 0)}")
                click.echo(f"   - Total users in workspace: {data.get('total_users', 0)}")

                if from_cache:
                    click.echo("   ℹ️  Data loaded from existing files (use --force to re-download)")
            else:
                click.echo(f"❌ Channel #{channel} not found or could not be accessed")
                ctx.exit(1)
        except Exception as e:
            click.echo(f"❌ Download failed: {e}")
            ctx.exit(1)
    else:
        click.echo("Starting download from source workspace...")
        try:
            data = migrator.download_workspace_data(force=force)
            click.echo(f"✅ Download completed! Data saved to {migrator.output_dir}")

            # Count what was actually downloaded vs cached
            users_count = len(data.get('users', []))
            channels_count = len(data.get('channels', []))
            messages_count = len(data.get('messages', {}))

            # Count total files across all channels
            total_files = 0
            for channel_data in data.get('messages', {}).values():
                messages = channel_data.get('messages', [])
                for message in messages:
                    total_files += len(message.get('files', []))

            click.echo(f"   - Users: {users_count}")
            click.echo(f"   - Channels: {channels_count}")
            click.echo(f"   - Message channels processed: {messages_count}")
            click.echo(f"   - Files downloaded: {total_files}")

            # Show breakdown of what was skipped vs downloaded
            if not force:
                workspace_exists = migrator._workspace_info_exists()
                users_exists = migrator._users_data_exists()
                channels_exists = migrator._channels_data_exists()

                if workspace_exists or users_exists or channels_exists:
                    click.echo("\n📁 Used cached data for:")
                    if workspace_exists:
                        click.echo("   - Workspace info")
                    if users_exists:
                        click.echo("   - Users")
                    if channels_exists:
                        click.echo("   - Channels")

        except Exception as e:
            click.echo(f"❌ Download failed: {e}")
            ctx.exit(1)

@cli.command()
@click.option('--channel', help='Upload only a specific channel (by name)')
@click.option('--dry-run', is_flag=True, help='Show what would be uploaded without actually uploading')
@click.option('--limit', type=int, help='Limit number of messages to upload (for testing)')
@click.pass_context
def upload(ctx, channel, dry_run, limit):
    """Upload data to destination Slack workspace"""
    migrator = ctx.obj['migrator']

    if dry_run:
        click.echo("🔍 Dry run mode - showing what would be uploaded...")

    if channel:
        click.echo(f"Starting upload of channel #{channel} to destination workspace...")

        # Check if we have data for this channel
        output_dir = Path(migrator.output_dir)
        messages_dir = output_dir / "messages"

        if not messages_dir.exists():
            click.echo("❌ No downloaded data found. Please run download first.")
            ctx.exit(1)

        # Find the channel file
        channel_file = None
        for file_path in messages_dir.glob(f"{channel}_*.json"):
            channel_file = file_path
            break

        if not channel_file:
            click.echo(f"❌ No data found for channel #{channel}")
            click.echo("Available channels:")
            for file_path in messages_dir.glob("*.json"):
                channel_name = file_path.stem.split('_')[0]
                click.echo(f"  - {channel_name}")
            ctx.exit(1)

        # Load channel data
        try:
            with open(channel_file, 'r') as f:
                channel_data = json.load(f)

            messages = channel_data.get("messages", [])

            # Apply limit if specified
            if limit and limit > 0:
                messages = messages[:limit]
                click.echo(f"ℹ️  Limited to first {limit} messages for testing")

            files_count = sum(len(msg.get("files", [])) for msg in messages)

            if dry_run:
                click.echo(f"📋 Would upload to #{channel}:")
                click.echo(f"   - Messages: {len(messages)}")
                click.echo(f"   - Files: {files_count}")
                return

            # Skip workspace connection test for now (missing scope)
            click.echo("📤 Starting upload...")
            click.echo(f"   - Messages: {len(messages)}")
            click.echo(f"   - Files: {files_count}")

            # Create a mock data structure for single channel upload
            limited_channel_data = channel_data.copy()
            limited_channel_data["messages"] = messages

            upload_data = {
                "messages": {channel_data["channel_info"]["id"]: limited_channel_data}
            }

            try:
                migrator.upload_workspace_data(upload_data)
                click.echo(f"✅ Upload completed for #{channel}!")
            except Exception as e:
                click.echo(f"❌ Upload failed: {e}")
                import traceback
                traceback.print_exc()
                ctx.exit(1)

        except Exception as e:
            click.echo(f"❌ Error reading channel data: {e}")
            ctx.exit(1)
    else:
        click.echo("Starting upload to destination workspace...")
        if dry_run:
            # Show what would be uploaded
            data = migrator.load_data()
            total_messages = sum(len(ch_data.get("messages", [])) for ch_data in data.get("messages", {}).values())
            total_files = sum(
                len(msg.get("files", []))
                for ch_data in data.get("messages", {}).values()
                for msg in ch_data.get("messages", [])
            )
            click.echo(f"📋 Would upload:")
            click.echo(f"   - Channels: {len(data.get('channels', []))}")
            click.echo(f"   - Messages: {total_messages}")
            click.echo(f"   - Files: {total_files}")
            return

        try:
            migrator.upload_workspace_data()
            click.echo("✅ Upload completed!")
        except Exception as e:
            click.echo(f"❌ Upload failed: {e}")
            ctx.exit(1)

@cli.command()
@click.pass_context
def migrate(ctx):
    """Run complete migration (download + upload)"""
    migrator = ctx.obj['migrator']

    click.echo("Starting complete migration...")
    try:
        migrator.migrate()
        click.echo("✅ Migration completed!")
    except Exception as e:
        click.echo(f"❌ Migration failed: {e}")
        ctx.exit(1)

@cli.command()
@click.pass_context
def info(ctx):
    """Show workspace information"""
    config = ctx.obj['config']
    migrator = ctx.obj['migrator']

    click.echo("=== Source Workspace ===")
    try:
        source_info = migrator.source_client.get_workspace_info()
        click.echo(f"Name: {source_info['team']['name']}")
        click.echo(f"Domain: {source_info['team']['domain']}")
        click.echo(f"ID: {source_info['team']['id']}")
    except Exception as e:
        click.echo(f"❌ Could not connect to source workspace: {e}")

    click.echo("\n=== Destination Workspace ===")
    try:
        dest_info = migrator.dest_client.get_workspace_info()
        click.echo(f"Name: {dest_info['team']['name']}")
        click.echo(f"Domain: {dest_info['team']['domain']}")
        click.echo(f"ID: {dest_info['team']['id']}")
    except Exception as e:
        click.echo(f"❌ Could not connect to destination workspace: {e}")

    click.echo(f"\n=== Configuration ===")
    click.echo(f"Output directory: {config.output_dir}")
    click.echo(f"Batch size: {config.batch_size}")
    click.echo(f"Rate limit delay: {config.rate_limit_delay}s")

@cli.command()
@click.pass_context
def status(ctx):
    """Show migration status and downloaded data"""
    migrator = ctx.obj['migrator']
    output_dir = Path(migrator.output_dir)

    if not output_dir.exists():
        click.echo("No migration data found.")
        return

    click.echo("=== Downloaded Data Status ===")

    # Check workspace info
    workspace_file = output_dir / "workspace_info.json"
    if workspace_file.exists():
        try:
            with open(workspace_file) as f:
                workspace_info = json.load(f)
            team_name = workspace_info.get("team", {}).get("name", "Unknown")
            click.echo(f"✅ Workspace info ({team_name})")
        except Exception as e:
            click.echo(f"⚠️  Workspace info (corrupted: {e})")
    else:
        click.echo("❌ Workspace info")

    # Check users
    users_file = output_dir / "users.json"
    if users_file.exists():
        try:
            with open(users_file) as f:
                users = json.load(f)
            click.echo(f"✅ Users ({len(users)} users)")
        except Exception as e:
            click.echo(f"⚠️  Users (corrupted: {e})")
    else:
        click.echo("❌ Users")

    # Check channels
    channels_file = output_dir / "channels.json"
    if channels_file.exists():
        try:
            with open(channels_file) as f:
                channels = json.load(f)
            click.echo(f"✅ Channels ({len(channels)} channels)")

            # Show channel breakdown
            public_channels = sum(1 for ch in channels if not ch.get("is_private", False) and not ch.get("is_archived", False))
            private_channels = sum(1 for ch in channels if ch.get("is_private", False) and not ch.get("is_archived", False))
            archived_channels = sum(1 for ch in channels if ch.get("is_archived", False))

            click.echo(f"   - Public: {public_channels}")
            click.echo(f"   - Private: {private_channels}")
            click.echo(f"   - Archived: {archived_channels}")
        except Exception as e:
            click.echo(f"⚠️  Channels (corrupted: {e})")
    else:
        click.echo("❌ Channels")

    # Check messages
    messages_dir = output_dir / "messages"
    if messages_dir.exists():
        message_files = list(messages_dir.glob("*.json"))
        click.echo(f"✅ Messages ({len(message_files)} channel message files)")

        # Analyze message files
        total_messages = 0
        total_files = 0
        channels_with_errors = 0
        successful_channels = 0

        for file_path in message_files:
            try:
                with open(file_path) as f:
                    channel_data = json.load(f)
                messages = channel_data.get("messages", [])
                if channel_data.get("error"):
                    channels_with_errors += 1
                else:
                    successful_channels += 1
                    total_messages += len(messages)
                    # Count files in messages
                    for message in messages:
                        total_files += len(message.get("files", []))
            except Exception:
                channels_with_errors += 1

        click.echo(f"   - Successful downloads: {successful_channels}")
        click.echo(f"   - Failed downloads: {channels_with_errors}")
        click.echo(f"   - Total messages: {total_messages}")
        click.echo(f"   - Total files: {total_files}")

        if channels_with_errors > 0:
            click.echo("   ⚠️  Some channels had download errors")
    else:
        click.echo("❌ Messages")

    # Check files directory
    files_dir = output_dir / "files"
    if files_dir.exists():
        # Count files by type
        file_counts = {}
        total_size = 0

        for file_path in files_dir.rglob("*"):
            if file_path.is_file():
                file_ext = file_path.suffix.lower() or 'no_extension'
                file_counts[file_ext] = file_counts.get(file_ext, 0) + 1
                try:
                    total_size += file_path.stat().st_size
                except:
                    pass

        total_file_count = sum(file_counts.values())

        if total_file_count > 0:
            # Convert bytes to human readable
            def format_size(size_bytes):
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if size_bytes < 1024:
                        return f"{size_bytes:.1f} {unit}"
                    size_bytes /= 1024
                return f"{size_bytes:.1f} TB"

            click.echo(f"✅ Files ({total_file_count} files, {format_size(total_size)})")

            # Show top file types
            sorted_types = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)
            for ext, count in sorted_types[:5]:  # Show top 5 file types
                ext_display = ext if ext != 'no_extension' else 'no extension'
                click.echo(f"   - {ext_display}: {count}")

            if len(sorted_types) > 5:
                click.echo(f"   - ... and {len(sorted_types) - 5} other types")

        else:
            click.echo("📁 Files directory exists but is empty")
    else:
        click.echo("❌ Files")

if __name__ == '__main__':
    cli()
