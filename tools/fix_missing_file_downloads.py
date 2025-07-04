#!/usr/bin/env python3
"""
Fix Missing File Downloads

This script identifies channels that have messages downloaded but missing file downloads
(files_downloaded: false) and processes the file download phase for them.

This typically happens when downloads were interrupted after message collection but
before file processing completed.
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime

# Add the parent directory to Python path so we can import from the main project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from migrator import SlackMigrator
from config import get_config

def find_channels_needing_file_processing(migration_data_dir: Path) -> List[Dict]:
    """Find channels that need file processing"""
    messages_dir = migration_data_dir / "messages"
    channels_needing_fix = []

    if not messages_dir.exists():
        print("❌ Messages directory not found")
        return channels_needing_fix

    print("🔍 Scanning channels for missing file downloads...")

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
                    channel_id = potential_channel_id
                else:
                    channel_name = parts[0]
                    channel_id = "unknown"
            else:
                channel_name = filename_without_ext
                channel_id = "unknown"

            messages = channel_data.get("messages", [])
            files_downloaded = channel_data.get("files_downloaded", False)
            download_completed = channel_data.get("download_completed", False)

            # Count files in messages
            total_files = 0
            files_with_local_path = 0

            for message in messages:
                for file_info in message.get("files", []):
                    total_files += 1
                    if file_info.get("local_path"):
                        files_with_local_path += 1

            # Identify channels that need fixing:
            # 1. Have messages
            # 2. Have files in messages
            # 3. But files_downloaded is false or files missing local_path
            needs_fix = (
                len(messages) > 0 and
                total_files > 0 and
                (not files_downloaded or files_with_local_path == 0)
            )

            if needs_fix:
                channels_needing_fix.append({
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "file_path": str(file_path),
                    "message_count": len(messages),
                    "total_files": total_files,
                    "files_with_local_path": files_with_local_path,
                    "files_downloaded": files_downloaded,
                    "download_completed": download_completed
                })

                print(f"   📋 {channel_name}: {len(messages)} messages, {total_files} files need processing")

        except Exception as e:
            print(f"⚠️  Error analyzing {file_path.name}: {e}")

    return channels_needing_fix

def process_channel_files(migrator: SlackMigrator, channel_info: Dict) -> bool:
    """Process file downloads for a specific channel"""
    channel_name = channel_info["channel_name"]
    channel_id = channel_info["channel_id"]
    file_path = Path(channel_info["file_path"])

    print(f"\n🔄 Processing files for #{channel_name}...")
    print(f"   Messages: {channel_info['message_count']}")
    print(f"   Files to download: {channel_info['total_files']}")

    try:
        # Load the channel data
        with open(file_path, 'r') as f:
            channel_data = json.load(f)

        messages = channel_data.get("messages", [])
        channel_metadata = channel_data.get("channel_info", {})

        if not messages:
            print(f"   ⚠️  No messages found in {channel_name}")
            return False

        # Process files using the migrator's file download logic
        print(f"   📥 Downloading files...")
        updated_messages = migrator._download_channel_files(messages, channel_name)

        # Update the channel data with processed files
        updated_channel_data = {
            **channel_data,
            "messages": updated_messages,
            "files_downloaded": True,
            "download_completed": True,
            "file_processing_timestamp": datetime.now().isoformat()
        }

        # Save the updated data
        with open(file_path, 'w') as f:
            json.dump(updated_channel_data, f, indent=2)

        # Count results
        total_files_after = sum(len(msg.get("files", [])) for msg in updated_messages)
        files_with_local_path_after = sum(
            1 for msg in updated_messages
            for file_info in msg.get("files", [])
            if file_info.get("local_path")
        )

        print(f"   ✅ Completed #{channel_name}")
        print(f"      Files processed: {files_with_local_path_after}/{total_files_after}")

        return True

    except Exception as e:
        print(f"   ❌ Failed to process #{channel_name}: {e}")
        return False

def main():
    """Main function"""
    print("🔧 Fix Missing File Downloads")
    print("=" * 50)

    # Initialize config and migrator
    try:
        config = get_config()
        migrator = SlackMigrator(config)
    except Exception as e:
        print(f"❌ Failed to initialize migrator: {e}")
        sys.exit(1)

    # Find channels needing file processing
    migration_data_dir = Path("migration_data")
    channels_needing_fix = find_channels_needing_file_processing(migration_data_dir)

    if not channels_needing_fix:
        print("✅ No channels found that need file processing!")
        return

    print(f"\n📊 Found {len(channels_needing_fix)} channels needing file processing:")

    # Show summary
    total_files_to_process = sum(ch["total_files"] for ch in channels_needing_fix)
    print(f"   Total files to download: {total_files_to_process}")
    print()

    # Ask for confirmation
    response = input("Proceed with file processing? (y/N): ").strip().lower()
    if response != 'y':
        print("❌ Aborted by user")
        return

    # Process each channel
    successful = 0
    failed = 0

    for i, channel_info in enumerate(channels_needing_fix, 1):
        print(f"\n[{i}/{len(channels_needing_fix)}] Processing {channel_info['channel_name']}...")

        try:
            if process_channel_files(migrator, channel_info):
                successful += 1
            else:
                failed += 1
        except KeyboardInterrupt:
            print(f"\n⚠️  Processing interrupted at channel #{channel_info['channel_name']}")
            print(f"   Completed: {successful}/{len(channels_needing_fix)} channels")
            break
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
            failed += 1

    # Summary
    print(f"\n🎯 File processing complete!")
    print(f"   ✅ Successful: {successful}")
    if failed > 0:
        print(f"   ❌ Failed: {failed}")

    if successful > 0:
        print("\n💡 You can now retry uploading the fixed channels!")

if __name__ == "__main__":
    main()
