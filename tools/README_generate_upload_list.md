# Generate Upload List Tool

## Overview

The `generate_upload_list.py` tool analyzes downloaded migration data and creates channel lists that can be used with the upload command. This helps you easily select which channels to upload based on various criteria.

## Features

- **Smart Channel Analysis**: Automatically parses downloaded channel data files
- **Flexible Filtering**: Filter by message count, file count, channel type, etc.
- **Multiple Sorting Options**: Sort by messages, files, or alphabetically
- **Statistics Display**: Show message and file counts for each channel
- **Various Output Formats**: Save to file or display on screen

## Usage

```bash
python tools/generate_upload_list.py [OPTIONS]
```

### Basic Examples

```bash
# Generate list of all downloaded channels
python tools/generate_upload_list.py --all

# Only channels with completed downloads
python tools/generate_upload_list.py --completed

# Only channels that have files
python tools/generate_upload_list.py --with-files

# Channels with at least 50 messages
python tools/generate_upload_list.py --all --min-messages 50

# Top 10 channels by message count
python tools/generate_upload_list.py --all --top 10 --by-messages

# Private channels only
python tools/generate_upload_list.py --all --only-private

# Exclude private channels
python tools/generate_upload_list.py --all --exclude-private
```

### Advanced Examples

```bash
# Channels with lots of files, sorted by file count, with statistics
python tools/generate_upload_list.py --with-files --min-files 5 --by-files --stats

# Save to file with custom title
python tools/generate_upload_list.py --all --top 20 --by-messages \
  --title "Top 20 Active Channels" --output priority_upload.txt

# Complex filtering: non-private channels with meaningful content
python tools/generate_upload_list.py --all --exclude-private \
  --min-messages 10 --alphabetical --stats --output public_channels.txt
```

## Command Line Options

### Channel Selection (Required)

- `--all`: Include all channels with data
- `--completed`: Only completed downloads
- `--partial`: Only partial downloads
- `--with-files`: Only channels with files
- `--with-messages`: Only channels with messages

### Filtering Options

- `--min-messages N`: Minimum number of messages
- `--min-files N`: Minimum number of files
- `--exclude-private`: Exclude private channels
- `--exclude-archived`: Exclude archived channels
- `--only-private`: Only private channels
- `--only-archived`: Only archived channels

### Sorting & Limiting

- `--by-messages`: Sort by message count (descending)
- `--by-files`: Sort by file count (descending)
- `--alphabetical`: Sort alphabetically
- `--top N`: Limit to top N channels

### Output Options

- `--output FILE`, `-o FILE`: Save to file
- `--stats`: Include message/file statistics
- `--title TITLE`: Custom title for the list
- `--data-dir DIR`: Migration data directory (default: migration_data)

## Output Format

### Simple Format

```
# Generated Upload List
# All available channels
# Generated: 2025-01-01 12:00:00
# Total channels: 8

#channel1
#channel2
#channel3
```

### With Statistics

```
# Generated Upload List
# Channels with files, min 5 files
# Generated: 2025-01-01 12:00:00
# Total channels: 4

# Channel Statistics:
# Format: #channel_name (messages: X, files: Y)

#memo_changyo  # 94 msgs, 11 files
#pj_bamboo_expo  # 90 msgs, 17 files [PRIVATE]
#fyi_deadline  # 475 msgs, 14 files
#pj_3dprintsoftsensor  # 315 msgs, 62 files [PRIVATE]
```

## Use Cases

### 1. Priority Upload Lists

Create lists focused on the most important channels first:

```bash
# High-traffic channels first
python tools/generate_upload_list.py --all --min-messages 100 \
  --by-messages --title "High Traffic Channels" -o priority.txt

# Channels with important files
python tools/generate_upload_list.py --with-files --min-files 10 \
  --by-files --title "Channels with Important Files" -o files.txt
```

### 2. Testing Upload Lists

Create smaller lists for testing upload functionality:

```bash
# Small test batch
python tools/generate_upload_list.py --all --top 5 \
  --title "Test Upload Batch" -o test_upload.txt
```

### 3. Channel Type Specific Lists

Separate uploads by channel type:

```bash
# Public channels only
python tools/generate_upload_list.py --all --exclude-private \
  --title "Public Channels" -o public.txt

# Private channels only
python tools/generate_upload_list.py --all --only-private \
  --title "Private Channels" -o private.txt
```

### 4. Content-Based Lists

Focus on channels with specific content characteristics:

```bash
# Active discussion channels
python tools/generate_upload_list.py --all --min-messages 50 \
  --exclude-archived --title "Active Channels" -o active.txt

# Archive channels with historical data
python tools/generate_upload_list.py --all --only-archived \
  --title "Archived Channels" -o archived.txt
```

## Integration with Upload Command

Use the generated lists with the upload command:

```bash
# Generate list
python tools/generate_upload_list.py --all --top 10 --by-messages -o top10.txt

# Upload using the list
python main.py upload --channels-file top10.txt --dry-run

# Actual upload
python main.py upload --channels-file top10.txt
```

## Tips

1. **Start with dry runs**: Always use `--dry-run` with upload command first
2. **Use statistics**: The `--stats` flag helps you understand channel content
3. **Test with small lists**: Use `--top N` for initial testing
4. **Filter by importance**: Use `--min-messages` to focus on active channels
5. **Separate by type**: Handle private and public channels separately if needed
