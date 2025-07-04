# Fix Missing File Downloads Tool

## Problem Description

During Slack workspace migration, some channels may end up with **messages downloaded but files missing**. This happens when the download process is interrupted or fails after message collection but before file processing completes.

### Symptoms

- Upload failures with errors about missing `local_path` attributes
- Channels show `files_downloaded: false` in their JSON files
- Messages contain file references but no downloaded files
- Files directory missing or incomplete for affected channels

### Root Cause

The download process has two phases:

1. **Message Download**: Collects all messages with incremental saving
2. **File Download**: Downloads and processes all file attachments

If interrupted between these phases (Ctrl+C, network errors, API limits, etc.), you get messages without files.

## Solution

The `fix_missing_file_downloads.py` script identifies and fixes affected channels by:

1. Scanning all channel files for missing file downloads
2. Processing file downloads for affected channels
3. Updating channel metadata to mark files as downloaded

## Usage

### Basic Usage

```bash
python tools/fix_missing_file_downloads.py
```

### What It Does

1. **Scans** all channel files in `migration_data/messages/`
2. **Identifies** channels with:
   - Messages downloaded ✓
   - Files present in messages ✓
   - But `files_downloaded: false` ❌
3. **Shows** summary of affected channels
4. **Asks** for confirmation before processing
5. **Downloads** all missing files for each channel
6. **Updates** channel files with `files_downloaded: true`

### Example Output

```
🔧 Fix Missing File Downloads
==================================================
🔍 Scanning channels for missing file downloads...
   📋 all_random: 4315 messages, 590 files need processing
   📋 memo_changyo: 156 messages, 23 files need processing
   📋 pj_bamboo_expo: 89 messages, 12 files need processing

📊 Found 3 channels needing file processing:
   Total files to download: 625

Proceed with file processing? (y/N): y

[1/3] Processing all_random...
🔄 Processing files for #all_random...
   Messages: 4315
   Files to download: 590
   📥 Downloading files...
   ✅ Completed #all_random
      Files processed: 587/590

[2/3] Processing memo_changyo...
...
```

## Safety Features

- **Non-destructive**: Only adds missing file downloads, doesn't modify existing data
- **Resume-friendly**: Can be interrupted and rerun safely
- **Confirmation**: Asks before processing
- **Progress tracking**: Shows detailed progress for each channel
- **Error handling**: Continues with other channels if one fails

## After Running

Once files are processed:

1. Channels will have `files_downloaded: true`
2. Messages will have `local_path` attributes for successful downloads
3. You can retry uploads without file-related errors

### Verification

```bash
# Check a specific channel
python tools/show_recent_messages.py all_random 5

# Or run upload dry-run to verify
python main.py upload --dry-run --channel all_random
```

## Integration with Upload

After running this fix, affected channels should upload successfully:

```bash
# Upload specific fixed channel
python main.py upload --channel all_random

# Or upload from a list
python main.py upload --channels-file your_channel_list.txt
```

## When to Use

Run this tool when you encounter:

- Upload errors about missing `local_path`
- Channels that seem incomplete despite successful downloads
- File-related upload failures after interrupted downloads
- Inconsistent file counts between channels

The tool is safe to run multiple times and will only process channels that actually need fixing.
