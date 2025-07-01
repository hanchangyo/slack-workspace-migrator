#!/usr/bin/env python3
"""
Generate Upload Lists from Downloaded Migration Data

This script analyzes the downloaded Slack migration data and generates
channel lists that can be used with the upload command.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add the parent directory to Python path so we can import from the main project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def analyze_downloaded_data(migration_data_dir: Path) -> Dict[str, Any]:
    """Analyze the downloaded migration data and return summary statistics"""

    results = {
        "total_channels": 0,
        "completed_channels": [],
        "partial_channels": [],
        "failed_channels": [],
        "channels_with_messages": [],
        "channels_with_files": [],
        "channel_stats": {}
    }

    messages_dir = migration_data_dir / "messages"
    if not messages_dir.exists():
        print(f"❌ No messages directory found at {messages_dir}")
        return results

    # Analyze each channel file
    for file_path in messages_dir.glob("*.json"):
        try:
            with open(file_path, 'r') as f:
                channel_data = json.load(f)

            # Extract channel name from filename
            filename_without_ext = file_path.stem
            parts = filename_without_ext.split('_')
            if len(parts) >= 2:
                potential_channel_id = parts[-1]
                if (potential_channel_id.startswith('C') and
                    len(potential_channel_id) >= 9 and
                    potential_channel_id.isupper() and
                    potential_channel_id.isalnum()):
                    channel_name = '_'.join(parts[:-1])
                else:
                    channel_name = parts[0]
            else:
                channel_name = filename_without_ext

            results["total_channels"] += 1

            # Get basic channel info
            channel_info = channel_data.get("channel_info", {})
            messages = channel_data.get("messages", [])
            download_completed = channel_data.get("download_completed", False)
            partial_download = channel_data.get("partial_download", False)
            was_archived = channel_data.get("was_archived", False)

            # Count files
            total_files = sum(len(msg.get("files", [])) for msg in messages)

            # Store channel stats
            results["channel_stats"][channel_name] = {
                "messages": len(messages),
                "files": total_files,
                "completed": download_completed,
                "partial": partial_download,
                "archived": was_archived,
                "private": channel_info.get("is_private", False),
                "file_path": str(file_path)
            }

            # Categorize channels
            if download_completed:
                results["completed_channels"].append(channel_name)
            elif partial_download or messages:
                results["partial_channels"].append(channel_name)
            else:
                results["failed_channels"].append(channel_name)

            if messages:
                results["channels_with_messages"].append(channel_name)

            if total_files > 0:
                results["channels_with_files"].append(channel_name)

        except Exception as e:
            print(f"⚠️  Error analyzing {file_path.name}: {e}")
            # Try to extract channel name for failed list
            try:
                filename_without_ext = file_path.stem
                parts = filename_without_ext.split('_')
                if len(parts) >= 2:
                    potential_channel_id = parts[-1]
                    if (potential_channel_id.startswith('C') and
                        len(potential_channel_id) >= 9 and
                        potential_channel_id.isupper() and
                        potential_channel_id.isalnum()):
                        channel_name = '_'.join(parts[:-1])
                    else:
                        channel_name = parts[0]
                else:
                    channel_name = filename_without_ext
                results["failed_channels"].append(channel_name)
            except:
                pass

    return results

def generate_upload_list(channels: List[str], title: str, description: str,
                        include_stats: bool = False,
                        channel_stats: Optional[Dict[str, Any]] = None) -> str:
    """Generate formatted upload list content"""

    content = [
        f"# {title}",
        f"# {description}",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Total channels: {len(channels)}",
        ""
    ]

    if include_stats and channel_stats:
        content.extend([
            "# Channel Statistics:",
            "# Format: #channel_name (messages: X, files: Y)",
            ""
        ])

        for channel in channels:
            stats = channel_stats.get(channel, {})
            msg_count = stats.get("messages", 0)
            file_count = stats.get("files", 0)
            status_indicators = []

            if stats.get("partial"):
                status_indicators.append("PARTIAL")
            if stats.get("archived"):
                status_indicators.append("ARCHIVED")
            if stats.get("private"):
                status_indicators.append("PRIVATE")

            status_text = f" [{', '.join(status_indicators)}]" if status_indicators else ""
            content.append(f"#{channel}  # {msg_count} msgs, {file_count} files{status_text}")
    else:
        # Simple format without stats
        for channel in channels:
            content.append(f"#{channel}")

    return "\n".join(content)

def main():
    parser = argparse.ArgumentParser(
        description="Generate upload lists from downloaded migration data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all                          # All downloadable channels
  %(prog)s --completed                    # Only completed downloads
  %(prog)s --with-files                   # Only channels with files
  %(prog)s --min-messages 10              # Channels with 10+ messages
  %(prog)s --top 20 --by-messages         # Top 20 by message count
  %(prog)s --exclude-private              # Exclude private channels
  %(prog)s --stats                        # Include message/file stats
        """
    )

    # Input/output options
    parser.add_argument('--data-dir', type=Path, default='migration_data',
                       help='Migration data directory (default: migration_data)')
    parser.add_argument('--output', '-o', type=Path,
                       help='Output file (default: print to stdout)')

    # Channel selection options
    parser.add_argument('--all', action='store_true',
                       help='Include all channels with data')
    parser.add_argument('--completed', action='store_true',
                       help='Only include completed downloads')
    parser.add_argument('--partial', action='store_true',
                       help='Only include partial downloads')
    parser.add_argument('--with-files', action='store_true',
                       help='Only include channels with files')
    parser.add_argument('--with-messages', action='store_true',
                       help='Only include channels with messages')

    # Filtering options
    parser.add_argument('--min-messages', type=int, default=0,
                       help='Minimum number of messages')
    parser.add_argument('--min-files', type=int, default=0,
                       help='Minimum number of files')
    parser.add_argument('--exclude-private', action='store_true',
                       help='Exclude private channels')
    parser.add_argument('--exclude-archived', action='store_true',
                       help='Exclude archived channels')
    parser.add_argument('--only-private', action='store_true',
                       help='Only include private channels')
    parser.add_argument('--only-archived', action='store_true',
                       help='Only include archived channels')

    # Sorting and limiting options
    parser.add_argument('--top', type=int,
                       help='Limit to top N channels')
    parser.add_argument('--by-messages', action='store_true',
                       help='Sort by message count (desc)')
    parser.add_argument('--by-files', action='store_true',
                       help='Sort by file count (desc)')
    parser.add_argument('--alphabetical', action='store_true',
                       help='Sort alphabetically')

    # Output format options
    parser.add_argument('--stats', action='store_true',
                       help='Include message and file statistics')
    parser.add_argument('--title', default='Generated Upload List',
                       help='Title for the upload list')

    args = parser.parse_args()

    # Validate arguments
    if not args.data_dir.exists():
        print(f"❌ Migration data directory not found: {args.data_dir}")
        sys.exit(1)

    selection_flags = [args.all, args.completed, args.partial, args.with_files, args.with_messages]
    if not any(selection_flags):
        print("❌ Please specify at least one channel selection option (--all, --completed, --partial, --with-files, --with-messages)")
        sys.exit(1)

    # Analyze downloaded data
    print(f"🔍 Analyzing migration data in {args.data_dir}...")
    analysis = analyze_downloaded_data(args.data_dir)

    if analysis["total_channels"] == 0:
        print("❌ No downloaded channels found")
        sys.exit(1)

    print(f"📊 Found {analysis['total_channels']} downloaded channels:")
    print(f"   ✅ Completed: {len(analysis['completed_channels'])}")
    print(f"   ⚠️  Partial: {len(analysis['partial_channels'])}")
    print(f"   ❌ Failed: {len(analysis['failed_channels'])}")
    print(f"   📝 With messages: {len(analysis['channels_with_messages'])}")
    print(f"   📎 With files: {len(analysis['channels_with_files'])}")
    print()

    # Select channels based on criteria
    selected_channels = set()

    if args.all:
        selected_channels.update(analysis["completed_channels"])
        selected_channels.update(analysis["partial_channels"])
    if args.completed:
        selected_channels.update(analysis["completed_channels"])
    if args.partial:
        selected_channels.update(analysis["partial_channels"])
    if args.with_files:
        selected_channels.update(analysis["channels_with_files"])
    if args.with_messages:
        selected_channels.update(analysis["channels_with_messages"])

    # Apply filters
    filtered_channels = []
    for channel in selected_channels:
        stats = analysis["channel_stats"].get(channel, {})

        # Message count filter
        if stats.get("messages", 0) < args.min_messages:
            continue

        # File count filter
        if stats.get("files", 0) < args.min_files:
            continue

        # Private channel filters
        is_private = stats.get("private", False)
        if args.exclude_private and is_private:
            continue
        if args.only_private and not is_private:
            continue

        # Archived channel filters
        is_archived = stats.get("archived", False)
        if args.exclude_archived and is_archived:
            continue
        if args.only_archived and not is_archived:
            continue

        filtered_channels.append(channel)

    if not filtered_channels:
        print("❌ No channels match the specified criteria")
        sys.exit(1)

    # Sort channels
    if args.by_messages:
        filtered_channels.sort(key=lambda ch: analysis["channel_stats"].get(ch, {}).get("messages", 0), reverse=True)
    elif args.by_files:
        filtered_channels.sort(key=lambda ch: analysis["channel_stats"].get(ch, {}).get("files", 0), reverse=True)
    elif args.alphabetical:
        filtered_channels.sort()

    # Limit results
    if args.top:
        filtered_channels = filtered_channels[:args.top]

    # Generate description
    criteria = []
    if args.completed:
        criteria.append("completed downloads")
    if args.partial:
        criteria.append("partial downloads")
    if args.with_files:
        criteria.append("channels with files")
    if args.with_messages:
        criteria.append("channels with messages")
    if args.min_messages > 0:
        criteria.append(f"min {args.min_messages} messages")
    if args.min_files > 0:
        criteria.append(f"min {args.min_files} files")
    if args.exclude_private:
        criteria.append("excluding private")
    if args.only_private:
        criteria.append("private only")
    if args.exclude_archived:
        criteria.append("excluding archived")
    if args.only_archived:
        criteria.append("archived only")
    if args.top:
        criteria.append(f"top {args.top}")

    description = f"Channels matching: {', '.join(criteria)}" if criteria else "All available channels"

    # Generate upload list
    upload_list_content = generate_upload_list(
        filtered_channels,
        args.title,
        description,
        args.stats,
        analysis["channel_stats"]
    )

    # Output results
    if args.output:
        with open(args.output, 'w') as f:
            f.write(upload_list_content)
        print(f"✅ Generated upload list with {len(filtered_channels)} channels: {args.output}")
    else:
        print(f"📋 Generated upload list with {len(filtered_channels)} channels:")
        print("=" * 60)
        print(upload_list_content)

if __name__ == "__main__":
    main()
