# Slack Workspace Migrator

A Python tool to download data from one Slack workspace and upload it to another workspace. This tool can migrate channels, users, and messages between Slack workspaces.

## Features

- 📥 **Download** complete workspace data (channels, users, messages)
- 📤 **Upload** data to destination workspace
- 🔄 **User mapping** based on email addresses
- 📊 **Progress tracking** with visual progress bars
- 🛡️ **Rate limiting** and error handling
- 💾 **Data persistence** - save and resume migrations
- 🎛️ **CLI interface** with multiple commands

## Prerequisites

- Python 3.8+
- Slack Bot tokens for both source and destination workspaces
- Appropriate permissions in both workspaces

## Installation

1. Clone or download this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set up your environment configuration (see Configuration section)

## Configuration

### 1. Create Slack Apps and Get Tokens

You need to create Slack apps in both your source and destination workspaces:

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click "Create New App" → "From scratch"
3. Add the following OAuth scopes for your bot:

**For Source Workspace (reading data):**

**Bot Token Scopes:**

- `channels:read`
- `channels:history`
- `channels:join`
- `groups:read`
- `groups:history`
- `im:read`
- `im:history`
- `mpim:read`
- `mpim:history`
- `users:read`
- `files:read`

**User Token Scopes (required for archive operations):**

- `channels:write` or `channels:manage`
- `groups:write`
- `im:write`
- `mpim:write`

**For Destination Workspace (writing data):**

**Bot Token Scopes:**

- `channels:write`
- `channels:manage`
- `chat:write`
- `chat:write.public`
- `files:write`
- `users:read`
- `team:read`

4. Install the apps to your workspaces
5. Copy the Bot User OAuth Tokens

**Important for Archive Downloads:**
If you plan to download from archived channels, you'll also need a User OAuth Token:

1. In your Slack app settings, go to "OAuth & Permissions"
2. Add the required user token scopes (see scopes list above)
3. Click "Reinstall App" if needed
4. Copy the "User OAuth Token" (starts with `xoxp-`)
5. Add it to your `.env` file as `SOURCE_USER_TOKEN`

### 2. Environment Configuration

Create a `.env` file in the project directory:

```bash
# Slack API Tokens
SOURCE_SLACK_TOKEN=xoxb-your-source-workspace-bot-token
DEST_SLACK_TOKEN=xoxb-your-destination-workspace-bot-token

# User token for source workspace (required for unarchiving channels)
# Get this from your Slack app OAuth settings - User OAuth Token
SOURCE_USER_TOKEN=xoxp-your-source-workspace-user-token

# Optional: Workspace names for reference
SOURCE_WORKSPACE_NAME=Source Company Slack
DEST_WORKSPACE_NAME=Destination Company Slack

# Migration Settings
BATCH_SIZE=100
RATE_LIMIT_DELAY=1.0
MAX_RETRIES=3

# Output Settings
OUTPUT_DIR=migration_data
LOG_LEVEL=INFO
```

## Usage

The migrator provides several CLI commands:

### Check Workspace Information

```bash
python main.py info
```

### Download Data Only

```bash
python main.py download
```

### Download from Specific Channels

```bash
# Download a single channel
python main.py download --channel general

# Download channels from a file list
python main.py download --channels-file channels.txt

# Enable downloading from archived channels
python main.py download --archive-download

# Download specific channels including archived ones
python main.py download --channels-file channels.txt --archive-download
```

### Channel List File Format

Create a text file with channel names (one per line):

```
# High priority channels
#general
#announcements

# Project channels
#project-alpha
#project-beta

# Archived channels (requires --archive-download)
#old-project
#archived-discussion
```

**Note**: When using `--archive-download`, archived channels will be temporarily unarchived for download, then re-archived automatically. This requires additional permissions (see Configuration section).

### Upload Data Only (from previously downloaded data)

```bash
python main.py upload
```

### Complete Migration (download + upload)

```bash
python main.py migrate
```

### Check Migration Status

```bash
python main.py status
```

### Help

```bash
python main.py --help
```

## How It Works

### 1. Download Phase

- Fetches workspace information
- Downloads all users and their profiles
- Downloads all channels (public and private)
- Downloads all messages from each channel
- Saves data to JSON files in the output directory

### 2. Upload Phase

- Creates user mapping based on email addresses
- Creates channels in destination workspace
- Uploads messages with original timestamps
- Preserves message order and basic formatting

## Data Structure

The tool saves data in the following structure:

```
migration_data/
├── workspace_info.json    # Source workspace metadata
├── users.json            # All users and profiles
├── channels.json         # All channels information
└── messages/             # Directory with message files
    ├── general_C1234567.json
    ├── random_C7654321.json
    └── ...
```

## Important Limitations

### 1. Message Attribution

- Messages are posted as bot messages with original timestamps
- Original user attribution is preserved in message formatting
- User impersonation is not supported by Slack API

### 2. Thread Handling

- Thread messages are currently posted as regular messages
- Thread relationships are not preserved (limitation of current implementation)

### 3. File Attachments

- File attachments are not migrated
- Only text content and basic formatting is preserved

### 4. Private Channels

- Private channels require the bot to be added to the channel
- Bot needs appropriate permissions in both workspaces

### 5. Archived Channels

- By default, archived channels are skipped
- Use `--archive-download` to temporarily unarchive and download them
- Requires a user token (SOURCE_USER_TOKEN) with scopes: `channels:write`, `groups:write`, `im:write`, `mpim:write`
- Bot tokens cannot unarchive channels - this is a Slack API limitation
- Channels are automatically re-archived after successful download

### 6. Rate Limits

- Slack has strict rate limits for API calls
- The tool includes automatic rate limiting and retry logic
- Large workspaces may take considerable time to migrate

## Advanced Usage

### Custom Output Directory

```bash
OUTPUT_DIR=custom_backup_dir python main.py download
```

### Verbose Logging

```bash
python main.py --log-level DEBUG migrate
```

### Separate Download and Upload

```bash
# First, download data
python main.py download

# Later, upload to different workspace
# (Update DEST_SLACK_TOKEN in .env)
python main.py upload
```

## Troubleshooting

### Common Issues

1. **"Missing required scopes"**

   - Ensure your Slack app has all required OAuth scopes
   - Reinstall the app to your workspace after adding scopes

2. **"Rate limited"**

   - The tool handles rate limits automatically
   - For large workspaces, consider increasing `RATE_LIMIT_DELAY`

3. **"Channel already exists"**

   - The tool skips existing channels automatically
   - Check logs to see which channels were skipped

4. **"User mapping failed"**

   - Users are mapped by email address
   - Ensure users exist in destination workspace with same emails

5. **"Cannot unarchive channel"**
   - Bot tokens cannot unarchive channels (Slack API limitation)
   - Add SOURCE_USER_TOKEN to your .env file with a user token (xoxp-...)
   - Ensure the user token has `channels:write` and `groups:write` scopes
   - The user must have permission to archive/unarchive channels in the workspace

### Logs

Check the log file for detailed information:

```bash
tail -f slack_migrator.log
```

## Security Considerations

- Store API tokens securely
- Use environment variables or encrypted configuration
- Ensure bot tokens have minimal required permissions
- Consider data privacy regulations when migrating workspaces
- Test with a small workspace first

## Contributing

Feel free to submit issues and enhancement requests!

## License

This project is provided as-is for educational and migration purposes. Please ensure compliance with Slack's Terms of Service and your organization's data policies.

## Disclaimer

- This tool is not affiliated with Slack Technologies
- Use at your own risk and always test with non-production data first
- Ensure you have proper authorization before migrating workspace data
- Consider Slack's official migration tools for enterprise use cases

```

```
