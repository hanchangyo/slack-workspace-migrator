#!/usr/bin/env python3

"""
Simple script to list channel names and IDs
"""

import sys
import os
import argparse

# Add parent directory to path so we can import from the main project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import get_config
from slack_client import SlackClient

def main():
    parser = argparse.ArgumentParser(description="List Slack channels in a workspace.")
    parser.add_argument(
        "--workspace",
        choices=["source", "dest"],
        default="source",
        help="Which workspace to list channels from (default: source)"
    )
    args = parser.parse_args()

    config = get_config()
    if args.workspace == "source":
        token = config.source_token
        workspace_name = config.source_workspace_name or "Source"
    else:
        token = config.dest_token
        workspace_name = config.dest_workspace_name or "Destination"

    client = SlackClient(token)

    print(f"Channels in {workspace_name} workspace:")
    print("-" * 50)

    channels = client.get_channels(exclude_archived=False)

    for channel in sorted(channels, key=lambda x: x.get('name', '')):
        name = channel.get('name', 'Unknown')
        channel_id = channel.get('id', 'Unknown')
        is_private = "🔒" if channel.get('is_private', False) else "📢"
        is_member = "✅" if channel.get('is_member', False) else "❌"
        is_archived = "🗄️" if channel.get('is_archived', False) else ""

        print(f"{is_private} #{name:<25} {channel_id} {is_member} {is_archived}")

    print("-" * 50)
    print(f"Total: {len(channels)} channels")
    print("\nLegend:")
    print("📢 = Public channel    🔒 = Private channel")
    print("✅ = Bot is member     ❌ = Bot not member")
    print("🗄️ = Archived channel")

if __name__ == "__main__":
    main()
