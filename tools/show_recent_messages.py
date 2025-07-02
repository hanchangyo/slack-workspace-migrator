#!/usr/bin/env python3
"""
Show Recent Messages from Downloaded Channel

This script displays the most recent messages from a downloaded channel file.
Useful for quickly inspecting what content was downloaded.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
import pytz

# Add the parent directory to Python path so we can import from the main project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def format_timestamp(slack_timestamp: str) -> str:
    """Convert Slack timestamp to readable format"""
    try:
        # Slack timestamps are in Unix timestamp format with microseconds
        timestamp = float(slack_timestamp)
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return slack_timestamp

def format_message(message: dict, users_data: list = None) -> str:
    """Format a message for display"""
    user_id = message.get("user", "unknown")
    text = message.get("text", "")
    ts = message.get("ts", "")

    # Get user name if users data is available
    user_name = user_id
    if users_data:
        for user in users_data:
            if user["id"] == user_id:
                profile = user.get("profile", {})
                user_name = (profile.get("display_name") or
                           profile.get("real_name") or
                           user.get("name", user_id))
                break

    # Format timestamp
    time_str = format_timestamp(ts)

    # Handle special message types
    subtype = message.get("subtype", "")
    if subtype == "channel_join":
        return f"[{time_str}] {user_name} joined the channel"
    elif subtype == "channel_leave":
        return f"[{time_str}] {user_name} left the channel"
    elif subtype == "thread_broadcast":
        return f"[{time_str}] {user_name} (thread broadcast): {text}"

    # Check if it's a thread reply
    thread_ts = message.get("thread_ts")
    if thread_ts and thread_ts != ts:
        return f"[{time_str}] {user_name} (in thread): {text}"

    # Check for files
    files = message.get("files", [])
    file_info = ""
    if files:
        file_names = [f.get("name", "unknown") for f in files]
        file_info = f" [📎 {', '.join(file_names)}]"

    return f"[{time_str}] {user_name}: {text}{file_info}"

def show_recent_messages(channel_name: str, count: int = 10, messages_dir: Path = None):
    """Show recent messages from a channel"""

    if messages_dir is None:
        messages_dir = Path("migration_data") / "messages"

    if not messages_dir.exists():
        print(f"❌ Messages directory not found: {messages_dir}")
        return

    # Find the channel file
    channel_file = None
    for file_path in messages_dir.glob("*.json"):
        # Extract channel name from filename (handle underscores properly)
        filename_without_ext = file_path.stem
        parts = filename_without_ext.split('_')

        if len(parts) >= 2:
            # Check if last part is a channel ID
            potential_channel_id = parts[-1]
            if (potential_channel_id.startswith('C') and
                len(potential_channel_id) >= 9 and
                potential_channel_id.isupper() and
                potential_channel_id.isalnum()):
                # Channel ID found, reconstruct channel name
                extracted_name = '_'.join(parts[:-1])
            else:
                # Fallback
                extracted_name = parts[0]
        else:
            extracted_name = filename_without_ext

        if extracted_name == channel_name:
            channel_file = file_path
            break

    if not channel_file:
        print(f"❌ Channel #{channel_name} not found")
        print("Available channels:")
        for file_path in messages_dir.glob("*.json"):
            filename_without_ext = file_path.stem
            parts = filename_without_ext.split('_')

            if len(parts) >= 2:
                potential_channel_id = parts[-1]
                if (potential_channel_id.startswith('C') and
                    len(potential_channel_id) >= 9 and
                    potential_channel_id.isupper() and
                    potential_channel_id.isalnum()):
                    extracted_name = '_'.join(parts[:-1])
                else:
                    extracted_name = parts[0]
            else:
                extracted_name = filename_without_ext

            print(f"   - {extracted_name}")
        return

    # Load channel data
    try:
        with open(channel_file, 'r', encoding='utf-8') as f:
            channel_data = json.load(f)
    except Exception as e:
        print(f"❌ Error reading channel file: {e}")
        return

    # Load users data for name resolution
    users_data = None
    users_file = Path("migration_data") / "users.json"
    if users_file.exists():
        try:
            with open(users_file, 'r', encoding='utf-8') as f:
                users_data = json.load(f)
        except Exception as e:
            print(f"⚠️  Could not load users data: {e}")

    # Get messages
    messages = channel_data.get("messages", [])
    if not messages:
        print(f"📭 Channel #{channel_name} has no messages")
        return

    # Sort messages by timestamp (newest first for recent messages)
    messages.sort(key=lambda x: float(x.get("ts", 0)), reverse=True)

    # Take the most recent messages
    recent_messages = messages[:count]

    # Display channel info
    channel_info = channel_data.get("channel_info", {})
    print(f"📋 Channel: #{channel_name}")
    print(f"📊 Total messages: {len(messages)}")
    print(f"🔍 Showing {len(recent_messages)} most recent messages:")
    print("=" * 60)

    # Display messages (reverse order so newest is at bottom)
    for message in reversed(recent_messages):
        print(format_message(message, users_data))

    print("=" * 60)

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python show_recent_messages.py <channel_name> [count] [messages_directory]")
        print("Examples:")
        print("  python show_recent_messages.py test-migration")
        print("  python show_recent_messages.py all_general 20")
        print("  python show_recent_messages.py memo_changyo 5 /path/to/messages")
        sys.exit(1)

    channel_name = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    messages_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    show_recent_messages(channel_name, count, messages_dir)

if __name__ == "__main__":
    main()
