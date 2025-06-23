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

**For Destination Workspace (writing data):**

- `channels:write`
- `channels:manage`
- `chat:write`
- `chat:write.public`
- `files:write`
- `users:read`
- `team:read`

4. Install the apps to your workspaces
5. Copy the Bot User OAuth Tokens

### 2. Environment Configuration

Create a `.env` file in the project directory:

```bash
# Slack API Tokens
SOURCE_SLACK_TOKEN=xoxb-your-source-workspace-bot-token
DEST_SLACK_TOKEN=xoxb-your-destination-workspace-bot-token

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

### 5. Rate Limits

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
