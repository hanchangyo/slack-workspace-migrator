#!/usr/bin/env python3
"""
Fix Double-Wrapped Channel Info Structure

This script fixes downloaded channel files that have double-wrapped channel_info structure:
{
  "channel_info": {
    "channel_info": { ... }
  }
}

And converts them to the correct structure:
{
  "channel_info": { ... }
}
"""

import os
import sys
import json
import shutil
from pathlib import Path
from typing import Dict, Any

def fix_channel_file(file_path: Path) -> bool:
    """
    Fix a single channel file if it has double-wrapped channel_info
    Returns True if file was modified, False if no changes needed
    """
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check if we have the double-wrapping issue
        channel_info = data.get("channel_info", {})
        if isinstance(channel_info, dict) and "channel_info" in channel_info:
            print(f"🔧 Fixing double-wrapped structure in {file_path.name}")

            # Create backup
            backup_path = file_path.with_suffix('.json.backup')
            shutil.copy2(file_path, backup_path)
            print(f"   📋 Created backup: {backup_path.name}")

            # Fix the structure by unwrapping
            data["channel_info"] = channel_info["channel_info"]

            # Write the fixed file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"   ✅ Fixed and saved {file_path.name}")
            return True
        else:
            print(f"   ✅ {file_path.name} structure is correct, no changes needed")
            return False

    except Exception as e:
        print(f"   ❌ Error processing {file_path.name}: {e}")
        return False

def main():
    """Main function to fix all channel files"""
    # Default to migration_data/messages directory
    messages_dir = Path("migration_data") / "messages"

    # Allow custom directory as command line argument
    if len(sys.argv) > 1:
        messages_dir = Path(sys.argv[1])

    if not messages_dir.exists():
        print(f"❌ Messages directory not found: {messages_dir}")
        print("Usage: python fix_double_wrapped_channels.py [messages_directory]")
        print("Example: python fix_double_wrapped_channels.py migration_data/messages")
        sys.exit(1)

    print(f"🔍 Scanning channel files in: {messages_dir}")

    # Find all JSON files
    json_files = list(messages_dir.glob("*.json"))

    if not json_files:
        print("❌ No JSON files found in the directory")
        sys.exit(1)

    print(f"📁 Found {len(json_files)} channel files")
    print()

    # Process each file
    fixed_count = 0
    error_count = 0

    for file_path in json_files:
        if fix_channel_file(file_path):
            fixed_count += 1

    print()
    print("🎯 Summary:")
    print(f"   📂 Total files processed: {len(json_files)}")
    print(f"   🔧 Files fixed: {fixed_count}")
    print(f"   ✅ Files already correct: {len(json_files) - fixed_count}")

    if fixed_count > 0:
        print()
        print("✅ Double-wrapping issue has been fixed!")
        print("📋 Backup files created with .backup extension")
        print("🚀 You can now retry the upload operation")
    else:
        print()
        print("ℹ️  No files needed fixing - all structures are correct")

if __name__ == "__main__":
    main()
