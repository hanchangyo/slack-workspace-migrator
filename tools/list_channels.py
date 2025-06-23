#!/usr/bin/env python3

"""
Simple script to list all channels in a Slack workspace
Shows channel names, IDs, types, and membership status
"""

import logging
from config import get_config
from slack_client import SlackClient

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def main():
    print("🔍 Listing all channels in Slack workspace...")
    print()

    try:
        # Get configuration
        config = get_config()
        client = SlackClient(config.source_token)

        # Get all channels (including archived ones)
        channels = client.get_channels(exclude_archived=False)

        # Separate channels by type
        public_channels = []
        private_channels = []
        archived_channels = []

        for channel in channels:
            if channel.get("is_archived", False):
                archived_channels.append(channel)
            elif channel.get("is_private", False):
                private_channels.append(channel)
            else:
                public_channels.append(channel)

        # Display summary
        print(f"📊 Channel Summary:")
        print(f"   Total channels: {len(channels)}")
        print(f"   Public channels: {len(public_channels)}")
        print(f"   Private channels: {len(private_channels)}")
        print(f"   Archived channels: {len(archived_channels)}")
        print()

        # Display public channels
        if public_channels:
            print("📢 Public Channels:")
            print("=" * 80)
            for channel in sorted(public_channels, key=lambda x: x.get('name', '')):
                name = channel.get('name', 'Unknown')
                channel_id = channel.get('id', 'Unknown')
                is_member = "✅ Member" if channel.get('is_member', False) else "❌ Not member"
                member_count = channel.get('num_members', 'Unknown')
                purpose = channel.get('purpose', {}).get('value', '')[:50]
                if len(channel.get('purpose', {}).get('value', '')) > 50:
                    purpose += "..."

                print(f"#{name:<20} {channel_id:<12} {is_member:<12} Members: {member_count:<5}")
                if purpose:
                    print(f"{'':>20} Purpose: {purpose}")
                print()

        # Display private channels
        if private_channels:
            print("🔒 Private Channels:")
            print("=" * 80)
            for channel in sorted(private_channels, key=lambda x: x.get('name', '')):
                name = channel.get('name', 'Unknown')
                channel_id = channel.get('id', 'Unknown')
                is_member = "✅ Member" if channel.get('is_member', False) else "❌ Not member"
                member_count = channel.get('num_members', 'Unknown')
                purpose = channel.get('purpose', {}).get('value', '')[:50]
                if len(channel.get('purpose', {}).get('value', '')) > 50:
                    purpose += "..."

                print(f"#{name:<20} {channel_id:<12} {is_member:<12} Members: {member_count:<5}")
                if purpose:
                    print(f"{'':>20} Purpose: {purpose}")
                print()

        # Display archived channels (summary only)
        if archived_channels:
            print("🗄️  Archived Channels:")
            print("=" * 80)
            for channel in sorted(archived_channels, key=lambda x: x.get('name', '')):
                name = channel.get('name', 'Unknown')
                channel_id = channel.get('id', 'Unknown')
                is_private = "🔒 Private" if channel.get('is_private', False) else "📢 Public"

                print(f"#{name:<20} {channel_id:<12} {is_private}")
            print()

        # Show channels bot can download from
        downloadable_channels = []
        for channel in channels:
            if not channel.get("is_archived", False):
                if channel.get("is_member", False) or not channel.get("is_private", False):
                    downloadable_channels.append(channel)

        print("✅ Channels available for download:")
        print("=" * 80)
        for channel in sorted(downloadable_channels, key=lambda x: x.get('name', '')):
            name = channel.get('name', 'Unknown')
            is_private = "🔒" if channel.get('is_private', False) else "📢"
            print(f"   {is_private} #{name}")

        print()
        print(f"Total downloadable channels: {len(downloadable_channels)}")

        # Show channels that need manual invitation
        needs_invitation = []
        for channel in channels:
            if (channel.get("is_private", False) and
                not channel.get("is_member", False) and
                not channel.get("is_archived", False)):
                needs_invitation.append(channel)

        if needs_invitation:
            print()
            print("⚠️  Private channels requiring manual bot invitation:")
            print("=" * 80)
            for channel in sorted(needs_invitation, key=lambda x: x.get('name', '')):
                name = channel.get('name', 'Unknown')
                print(f"   🔒 #{name} - Use: /invite @YourBotName")

    except Exception as e:
        print(f"❌ Error listing channels: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
