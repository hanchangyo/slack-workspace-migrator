import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import pytz
from tqdm import tqdm
import requests
import time
from urllib.parse import urlparse

from slack_client import SlackClient
from config import SlackConfig

logger = logging.getLogger(__name__)

class SlackMigrator:
    """Main class for migrating Slack workspace data"""

    def __init__(self, config: SlackConfig):
        self.config = config
        self.source_client = SlackClient(
            config.source_token,
            config.rate_limit_delay,
            config.max_retries
        )
        self.dest_client = SlackClient(
            config.dest_token,
            config.rate_limit_delay,
            config.max_retries
        )
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Create files directory
        self.files_dir = self.output_dir / "files"
        self.files_dir.mkdir(exist_ok=True)

        # Mapping for user IDs between workspaces
        self.user_mapping: Dict[str, str] = {}
        self.channel_mapping: Dict[str, str] = {}

        # Track downloaded files to avoid duplicates
        self.downloaded_files: Dict[str, str] = {}  # file_id -> local_path

        # JST timezone
        self.jst = pytz.timezone('Asia/Tokyo')

    def _workspace_info_exists(self) -> bool:
        """Check if workspace info is already downloaded"""
        return (self.output_dir / "workspace_info.json").exists()

    def _users_data_exists(self) -> bool:
        """Check if users data is already downloaded"""
        return (self.output_dir / "users.json").exists()

    def _channels_data_exists(self) -> bool:
        """Check if channels data is already downloaded"""
        return (self.output_dir / "channels.json").exists()

    def _channel_messages_exist(self, channel_id: str) -> bool:
        """Check if messages for a specific channel are already downloaded"""
        messages_dir = self.output_dir / "messages"
        if not messages_dir.exists():
            return False

        # Look for any file that contains this channel ID
        for file_path in messages_dir.glob("*_*.json"):
            if channel_id in file_path.name:
                return True
        return False

    def _is_channel_accessible(self, channel: Dict[str, Any]) -> tuple[bool, str]:
        """
        Check if a channel is accessible for message download
        Returns (is_accessible, reason)
        """
        # Check if channel is archived
        if channel.get("is_archived", False):
            return False, "Channel is archived"

        # Check if channel is private and we might not have access
        if channel.get("is_private", False):
            return True, "Private channel - may require bot to be added"

        # Public channels should be accessible
        return True, "Channel is accessible"

    def _get_safe_filename(self, filename: str) -> str:
        """Get a safe filename for saving files"""
        # Remove or replace unsafe characters
        unsafe_chars = '<>:"/\\|?*'
        safe_filename = filename
        for char in unsafe_chars:
            safe_filename = safe_filename.replace(char, '_')

        # Limit length to avoid filesystem issues
        if len(safe_filename) > 200:
            name, ext = os.path.splitext(safe_filename)
            safe_filename = name[:200-len(ext)] + ext

        return safe_filename

    def _download_file(self, file_info: Dict[str, Any], channel_name: str) -> Optional[str]:
        """
        Download a single file from Slack
        Returns the local file path if successful, None otherwise
        """
        file_id = file_info.get("id")
        if not file_id:
            return None

        # Check if already downloaded
        if file_id in self.downloaded_files:
            return self.downloaded_files[file_id]

        # Get download URL - try different URL fields
        download_url = None
        for url_field in ["url_private_download", "url_private", "permalink_public"]:
            if file_info.get(url_field):
                download_url = file_info[url_field]
                break

        if not download_url:
            logger.warning(f"No download URL found for file {file_id}")
            return None

        # Get file details
        filename = file_info.get("name", f"file_{file_id}")
        file_title = file_info.get("title", filename)
        filetype = file_info.get("filetype", "unknown")

        # Create safe filename
        if not filename.endswith(f".{filetype}") and filetype != "unknown":
            filename = f"{filename}.{filetype}"
        safe_filename = self._get_safe_filename(filename)

        # Organize by channel
        channel_files_dir = self.files_dir / channel_name
        channel_files_dir.mkdir(exist_ok=True)

        local_path = channel_files_dir / safe_filename

        # If file already exists, add number suffix
        counter = 1
        original_path = local_path
        while local_path.exists():
            name_part = original_path.stem
            ext_part = original_path.suffix
            local_path = original_path.parent / f"{name_part}_{counter}{ext_part}"
            counter += 1

        try:
            # Download with authorization header
            headers = {
                "Authorization": f"Bearer {self.config.source_token}",
                "User-Agent": "SlackMigrator/1.0"
            }

            logger.debug(f"Downloading file: {file_title} -> {local_path}")

            # Rate limit file downloads (be conservative)
            time.sleep(1.0)

            response = requests.get(download_url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()

            # Write file in chunks
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            file_size = local_path.stat().st_size
            logger.info(f"Downloaded {file_title} ({file_size} bytes) to {local_path}")

            # Track downloaded file
            self.downloaded_files[file_id] = str(local_path)

            return str(local_path)

        except Exception as e:
            logger.error(f"Failed to download file {file_title}: {e}")
            # Clean up partial file
            if local_path.exists():
                local_path.unlink()
            return None

    def _process_message_files(self, message: Dict[str, Any], channel_name: str) -> Dict[str, Any]:
        """
        Process and download files from a message
        Returns updated message with local file paths
        """
        if "files" not in message:
            return message

        files = message["files"]
        if not files:
            return message

        updated_files = []

        for file_info in files:
            # Download the file
            local_path = self._download_file(file_info, channel_name)

            # Create updated file info
            updated_file_info = file_info.copy()
            if local_path:
                updated_file_info["local_path"] = local_path
                updated_file_info["download_status"] = "success"
            else:
                updated_file_info["download_status"] = "failed"

            updated_files.append(updated_file_info)

        # Update message with new file info
        updated_message = message.copy()
        updated_message["files"] = updated_files

        return updated_message

    def _download_channel_files(self, messages: List[Dict[str, Any]], channel_name: str) -> List[Dict[str, Any]]:
        """
        Download all files from messages in a channel
        Returns updated messages with local file paths
        """
        if not messages:
            return messages

        # Count files first
        total_files = 0
        for message in messages:
            if "files" in message and message["files"]:
                total_files += len(message["files"])

        if total_files == 0:
            return messages

        logger.info(f"Found {total_files} files to download from #{channel_name}")

        updated_messages = []
        downloaded_count = 0
        failed_count = 0

        with tqdm(total=total_files, desc=f"Downloading files from #{channel_name}") as pbar:
            for message in messages:
                if "files" in message and message["files"]:
                    # Process message files
                    updated_message = self._process_message_files(message, channel_name)

                    # Count results
                    for file_info in updated_message.get("files", []):
                        if file_info.get("download_status") == "success":
                            downloaded_count += 1
                        else:
                            failed_count += 1
                        pbar.update(1)

                    updated_messages.append(updated_message)
                else:
                    updated_messages.append(message)

        logger.info(f"File download completed for #{channel_name}: {downloaded_count} successful, {failed_count} failed")
        return updated_messages

    def _download_workspace_info(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Download workspace info if not already present"""
        if not force and self._workspace_info_exists():
            logger.info("Workspace info already exists, skipping download")
            with open(self.output_dir / "workspace_info.json", "r") as f:
                return json.load(f)

        logger.info("Downloading workspace info...")
        try:
            workspace_info = self.source_client.get_workspace_info()

            # Save immediately
            with open(self.output_dir / "workspace_info.json", "w") as f:
                json.dump(workspace_info, f, indent=2)

            logger.info("Workspace info downloaded and saved")
            return workspace_info
        except Exception as e:
            logger.error(f"Failed to download workspace info: {e}")
            return None

    def _download_users_data(self, force: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Download users data if not already present"""
        if not force and self._users_data_exists():
            logger.info("Users data already exists, skipping download")
            with open(self.output_dir / "users.json", "r") as f:
                return json.load(f)

        logger.info("Downloading users...")
        try:
            users = self.source_client.get_users()

            # Save immediately
            with open(self.output_dir / "users.json", "w") as f:
                json.dump(users, f, indent=2)

            logger.info(f"Downloaded and saved {len(users)} users")
            return users
        except Exception as e:
            logger.error(f"Failed to download users: {e}")
            return None

    def _download_channels_data(self, force: bool = False) -> Optional[List[Dict[str, Any]]]:
        """Download channels data if not already present"""
        if not force and self._channels_data_exists():
            logger.info("Channels data already exists, skipping download")
            with open(self.output_dir / "channels.json", "r") as f:
                return json.load(f)

        logger.info("Downloading channels...")
        try:
            channels = self.source_client.get_channels()

            # Save immediately
            with open(self.output_dir / "channels.json", "w") as f:
                json.dump(channels, f, indent=2)

            logger.info(f"Downloaded and saved {len(channels)} channels")
            return channels
        except Exception as e:
            logger.error(f"Failed to download channels: {e}")
            return None

    def download_workspace_data(self, force: bool = False) -> Dict[str, Any]:
        """Download all data from source workspace with incremental saving"""
        logger.info("Starting workspace data download...")

        data = {
            "workspace_info": None,
            "users": [],
            "channels": [],
            "messages": {}
        }

        # Download workspace info
        data["workspace_info"] = self._download_workspace_info(force=force)

        # Download users
        users = self._download_users_data(force=force)
        if users:
            data["users"] = users

        # Download channels
        channels = self._download_channels_data(force=force)
        if channels:
            data["channels"] = channels

        # Download messages for each channel
        if channels:
            logger.info("Downloading messages and files...")
            messages_dir = self.output_dir / "messages"
            messages_dir.mkdir(exist_ok=True)

            for channel in tqdm(channels, desc="Processing channels"):
                channel_id = channel["id"]
                channel_name = channel.get("name", channel_id)

                # Load existing data to check completion status
                existing_data = self._load_existing_channel_data(channel_name, channel_id)

                # Check if download was already completed and we're not forcing
                if not force and existing_data.get("download_completed", False):
                    logger.info(f"Channel #{channel_name} already completed, loading from file")
                    data["messages"][channel_id] = existing_data
                    continue

                # Check if channel is accessible
                is_accessible, reason = self._is_channel_accessible(channel)
                if not is_accessible:
                    logger.warning(f"Skipping #{channel_name}: {reason}")
                    continue

                logger.info(f"Downloading messages from #{channel_name} ({reason})")

                # Determine starting point for download (resume if possible)
                oldest_timestamp = None
                if not force and existing_data.get("messages"):
                    oldest_timestamp = self._get_last_message_timestamp(channel_name, channel_id)
                    if oldest_timestamp:
                        logger.info(f"Resuming #{channel_name} from timestamp {oldest_timestamp}")

                # Create progress callback for incremental saving
                def save_progress(message_batch: List[Dict[str, Any]]):
                    if message_batch:
                        self._save_incremental_messages(channel_name, channel_id, message_batch, channel, is_complete=False)

                try:
                    # Download messages with incremental saving
                    messages = self.source_client.get_channel_messages(
                        channel_id,
                        oldest=oldest_timestamp,
                        progress_callback=save_progress
                    )

                    # Load all messages we have so far
                    all_messages = self._load_existing_channel_data(channel_name, channel_id).get("messages", [])

                    # Download files from messages
                    logger.info(f"Processing files for {len(all_messages)} messages in #{channel_name}...")
                    updated_messages = self._download_channel_files(all_messages, channel_name)

                    # Final save with file information and completion flag
                    channel_data = {
                        "channel_info": channel,
                        "messages": updated_messages,
                        "download_timestamp": datetime.now().isoformat(),
                        "files_downloaded": True,
                        "download_completed": True
                    }

                    # Save final version
                    filename = f"{channel_name}_{channel_id}.json"
                    with open(messages_dir / filename, "w") as f:
                        json.dump(channel_data, f, indent=2)

                    data["messages"][channel_id] = channel_data

                    # Count files
                    file_count = sum(len(msg.get("files", [])) for msg in updated_messages)
                    logger.info(f"Downloaded and saved {len(updated_messages)} messages and {file_count} files from #{channel_name}")

                except KeyboardInterrupt:
                    logger.warning(f"Download interrupted during #{channel_name}. Progress has been saved and can be resumed.")
                    # Load partial data we have
                    partial_data = self._load_existing_channel_data(channel_name, channel_id)
                    if partial_data.get("messages"):
                        data["messages"][channel_id] = partial_data
                    # Re-raise to stop the overall download
                    raise

                except Exception as e:
                    logger.error(f"Failed to download messages from #{channel_name}: {e}")
                    # Load any partial data we have
                    partial_data = self._load_existing_channel_data(channel_name, channel_id)
                    if partial_data.get("messages"):
                        logger.info(f"Saving {len(partial_data['messages'])} partially downloaded messages from #{channel_name}")
                        partial_data["error"] = str(e)
                        partial_data["download_timestamp"] = datetime.now().isoformat()
                        data["messages"][channel_id] = partial_data
                    else:
                        # Save error info
                        error_data = {
                            "channel_info": channel,
                            "messages": [],
                            "error": str(e),
                            "download_timestamp": datetime.now().isoformat(),
                            "files_downloaded": False,
                            "download_completed": False
                        }
                        filename = f"{channel_name}_{channel_id}.json"
                        with open(messages_dir / filename, "w") as f:
                            json.dump(error_data, f, indent=2)
                        data["messages"][channel_id] = error_data

        logger.info("Workspace data download completed!")
        return data

    def _load_existing_channel_data(self, channel_name: str, channel_id: str) -> Dict[str, Any]:
        """Load existing channel data if it exists"""
        messages_dir = self.output_dir / "messages"
        filename = f"{channel_name}_{channel_id}.json"
        file_path = messages_dir / filename

        if file_path.exists():
            try:
                with open(file_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load existing channel data: {e}")

        return {
            "channel_info": {},
            "messages": [],
            "download_timestamp": None,
            "files_downloaded": False,
            "download_completed": False
        }

    def _save_incremental_messages(self, channel_name: str, channel_id: str, new_messages: List[Dict[str, Any]],
                                 channel_info: Dict[str, Any], is_complete: bool = False):
        """Save messages incrementally to avoid data loss on interruption"""
        messages_dir = self.output_dir / "messages"
        messages_dir.mkdir(exist_ok=True)
        filename = f"{channel_name}_{channel_id}.json"
        file_path = messages_dir / filename

        # Load existing data
        existing_data = self._load_existing_channel_data(channel_name, channel_id)

        # Update channel info
        existing_data["channel_info"] = channel_info

        # Append new messages (avoid duplicates by timestamp)
        existing_messages = existing_data.get("messages", [])
        existing_timestamps = {msg.get("ts") for msg in existing_messages if msg.get("ts")}

        for message in new_messages:
            if message.get("ts") not in existing_timestamps:
                existing_messages.append(message)
                existing_timestamps.add(message.get("ts"))

        # Sort messages by timestamp (oldest first)
        existing_messages.sort(key=lambda x: float(x.get("ts", 0)))

        # Update the data
        existing_data["messages"] = existing_messages
        existing_data["last_update_timestamp"] = datetime.now().isoformat()
        existing_data["download_completed"] = is_complete

        # Save to file
        try:
            with open(file_path, "w") as f:
                json.dump(existing_data, f, indent=2)
            logger.debug(f"Saved {len(new_messages)} new messages to {filename} (total: {len(existing_messages)})")
        except Exception as e:
            logger.error(f"Failed to save incremental messages: {e}")

    def _get_last_message_timestamp(self, channel_name: str, channel_id: str) -> Optional[str]:
        """Get the timestamp of the last downloaded message for resuming"""
        existing_data = self._load_existing_channel_data(channel_name, channel_id)
        messages = existing_data.get("messages", [])

        if messages:
            # Messages should be sorted by timestamp, get the newest one
            latest_message = max(messages, key=lambda x: float(x.get("ts", 0)))
            return latest_message.get("ts")

        return None

    def download_single_channel(self, channel_name: str, force: bool = False) -> Optional[Dict[str, Any]]:
        """Download data from a single channel by name with incremental saving"""
        logger.info(f"Starting single channel download for #{channel_name}...")

        # Ensure workspace info and users are downloaded first
        workspace_info = self._download_workspace_info(force=force)
        users = self._download_users_data(force=force)

        if not workspace_info or not users:
            logger.error("Failed to download required workspace info or users data")
            return None

        # Get all channels to find the target channel
        logger.info("Finding target channel...")
        all_channels = self.source_client.get_channels()

        target_channel = None
        for channel in all_channels:
            if channel.get("name") == channel_name:
                target_channel = channel
                break

        if not target_channel:
            logger.error(f"Channel #{channel_name} not found")
            return None

        channel_id = target_channel["id"]
        is_member = target_channel.get("is_member", False)
        is_private = target_channel.get("is_private", False)

        logger.info(f"Found channel #{channel_name} with ID {channel_id}")
        logger.info(f"Channel status - Private: {is_private}, Bot is member: {is_member}")

        # If bot is not a member, try to join the channel
        if not is_member:
            if is_private:
                logger.error(f"Channel #{channel_name} is private and bot is not a member. Manual invitation required.")
                return None
            else:
                logger.info(f"Bot is not in #{channel_name}, attempting to join...")
                try:
                    self.source_client.join_channel(channel_id)
                    logger.info(f"Successfully joined #{channel_name}")
                    # Update the channel info to reflect membership
                    target_channel["is_member"] = True
                except Exception as e:
                    logger.error(f"Failed to join #{channel_name}: {e}")
                    return None

        # Load existing data to check what we already have
        existing_data = self._load_existing_channel_data(channel_name, channel_id)

        # Check if download was already completed and we're not forcing
        if not force and existing_data.get("download_completed", False):
            logger.info(f"Channel #{channel_name} download already completed, loading from file")
            messages = existing_data.get("messages", [])
            file_count = sum(len(msg.get("files", [])) for msg in messages)

            return {
                "channel_info": target_channel,
                "messages": messages,
                "total_users": len(users),
                "file_count": file_count,
                "from_cache": True
            }

        # Check if channel is accessible
        is_accessible, reason = self._is_channel_accessible(target_channel)
        if not is_accessible:
            logger.error(f"Cannot access #{channel_name}: {reason}")
            return None

        logger.info(f"Channel #{channel_name} is accessible: {reason}")

        # Determine starting point for download
        oldest_timestamp = None
        if not force and existing_data.get("messages"):
            oldest_timestamp = self._get_last_message_timestamp(channel_name, channel_id)
            if oldest_timestamp:
                logger.info(f"Resuming download from timestamp {oldest_timestamp}")

        # Create progress callback for incremental saving
        def save_progress(message_batch: List[Dict[str, Any]]):
            if message_batch:
                self._save_incremental_messages(channel_name, channel_id, message_batch, target_channel, is_complete=False)

        # Download messages for the target channel with incremental saving
        logger.info(f"Downloading messages from #{channel_name}...")
        try:
            messages = self.source_client.get_channel_messages(
                channel_id,
                oldest=oldest_timestamp,
                progress_callback=save_progress
            )

            # Mark download as complete
            all_messages = self._load_existing_channel_data(channel_name, channel_id).get("messages", [])

            # Download files from messages
            logger.info(f"Processing files for {len(all_messages)} messages...")
            updated_messages = self._download_channel_files(all_messages, channel_name)

            # Final save with file information and completion flag
            final_save_data = {
                "channel_info": target_channel,
                "messages": updated_messages,
                "download_timestamp": datetime.now().isoformat(),
                "files_downloaded": True,
                "download_completed": True,
                "from_cache": False,
                "partial_download": False
            }
            self._save_incremental_messages(channel_name, channel_id, [], final_save_data)

            logger.info(f"✅ Successfully downloaded {len(updated_messages)} messages from #{channel_name}")

            return final_save_data

        except SlackApiError as e:
            error_code = e.response.get("error", "unknown_error")

            if error_code == "not_in_channel":
                # Try to handle the not_in_channel error
                if self._handle_not_in_channel_error(target_channel):
                    logger.info(f"🔄 Retrying download after joining #{channel_name}...")
                    # Retry the download after joining
                    try:
                        messages = self.source_client.get_channel_messages(
                            channel_id,
                            oldest=oldest_timestamp,
                            progress_callback=save_progress
                        )

                        all_messages = self._load_existing_channel_data(channel_name, channel_id).get("messages", [])
                        updated_messages = self._download_channel_files(all_messages, channel_name)

                        final_save_data = {
                            "channel_info": target_channel,
                            "messages": updated_messages,
                            "download_timestamp": datetime.now().isoformat(),
                            "files_downloaded": True,
                            "download_completed": True,
                            "from_cache": False,
                            "partial_download": False
                        }
                        self._save_incremental_messages(channel_name, channel_id, [], final_save_data)

                        logger.info(f"✅ Successfully downloaded {len(updated_messages)} messages from #{channel_name} after auto-join")
                        return final_save_data

                    except Exception as retry_e:
                        logger.error(f"❌ Retry failed for #{channel_name}: {retry_e}")
                        self.diagnose_channel_access(channel_name)
                        raise
                else:
                    logger.error(f"❌ Cannot resolve access issue for #{channel_name}")
                    self.diagnose_channel_access(channel_name)
                    raise
            else:
                logger.error(f"❌ API error downloading #{channel_name}: {error_code}")
                self.diagnose_channel_access(channel_name)
                raise

        except Exception as e:
            logger.error(f"❌ Unexpected error downloading #{channel_name}: {e}")
            self.diagnose_channel_access(channel_name)
            raise

    def _save_data(self, data: Dict[str, Any]):
        """Save downloaded data to JSON files (legacy method for compatibility)"""
        logger.info("Saving data to files...")

        # Save workspace info
        if data.get("workspace_info"):
            with open(self.output_dir / "workspace_info.json", "w") as f:
                json.dump(data["workspace_info"], f, indent=2)

        # Save users
        if data.get("users"):
            with open(self.output_dir / "users.json", "w") as f:
                json.dump(data["users"], f, indent=2)

        # Save channels
        if data.get("channels"):
            with open(self.output_dir / "channels.json", "w") as f:
                json.dump(data["channels"], f, indent=2)

        # Save messages by channel
        if data.get("messages"):
            messages_dir = self.output_dir / "messages"
            messages_dir.mkdir(exist_ok=True)

            for channel_id, channel_data in data["messages"].items():
                channel_name = channel_data["channel_info"].get("name", channel_id)
                filename = f"{channel_name}_{channel_id}.json"
                with open(messages_dir / filename, "w") as f:
                    json.dump(channel_data, f, indent=2)

    def load_data(self) -> Dict[str, Any]:
        """Load previously downloaded data from files"""
        logger.info("Loading data from files...")

        data = {
            "workspace_info": None,
            "users": [],
            "channels": [],
            "messages": {}
        }

        # Load workspace info
        workspace_file = self.output_dir / "workspace_info.json"
        if workspace_file.exists():
            with open(workspace_file, "r") as f:
                data["workspace_info"] = json.load(f)

        # Load users
        users_file = self.output_dir / "users.json"
        if users_file.exists():
            with open(users_file, "r") as f:
                data["users"] = json.load(f)

        # Load channels
        channels_file = self.output_dir / "channels.json"
        if channels_file.exists():
            with open(channels_file, "r") as f:
                data["channels"] = json.load(f)

        # Load messages
        messages_dir = self.output_dir / "messages"
        if messages_dir.exists():
            for file_path in messages_dir.glob("*.json"):
                with open(file_path, "r") as f:
                    channel_data = json.load(f)
                    channel_id = channel_data["channel_info"]["id"]
                    data["messages"][channel_id] = channel_data

        return data

    def upload_workspace_data(self, data: Optional[Dict[str, Any]] = None):
        """Upload data to destination workspace"""
        if data is None:
            data = self.load_data()

        logger.info("Starting workspace data upload...")

        # Create user mapping (match by email if possible) - only if users data exists
        if "users" in data and data["users"]:
            self._create_user_mapping(data["users"])
        else:
            logger.info("No users data provided, skipping user mapping")

        # Create channels - only if channels data exists
        if "channels" in data and data["channels"]:
            self._create_channels(data["channels"])
        elif "messages" in data:
            # For single channel uploads, handle channel creation here
            self._handle_single_channel_creation(data["messages"])

        # Upload messages
        if "messages" in data:
            self._upload_messages(data["messages"])

        logger.info("Workspace migration completed!")

    def _handle_single_channel_creation(self, messages_data: Dict[str, Any]):
        """Handle channel creation for single channel uploads"""
        logger.info("Handling single channel creation and bot joining...")

        for source_channel_id, channel_data in messages_data.items():
            channel_info = channel_data.get("channel_info", {})
            channel_name = channel_info.get("name")

            if not channel_name:
                logger.warning(f"No channel name found for {source_channel_id}")
                continue

            logger.info(f"Processing channel #{channel_name}")

            # Check if channel exists in destination workspace
            dest_channel_id = self._ensure_channel_exists(channel_info)

            if dest_channel_id:
                self.channel_mapping[source_channel_id] = dest_channel_id
                logger.info(f"Channel #{channel_name} ready for upload (ID: {dest_channel_id})")
            else:
                logger.error(f"Failed to create or access channel #{channel_name}")

    def _ensure_channel_exists(self, channel_info: Dict[str, Any]) -> Optional[str]:
        """
        Ensure channel exists in destination workspace and bot has access
        Returns channel ID if successful, None otherwise
        """
        channel_name = channel_info.get("name")
        is_private = channel_info.get("is_private", False)

        logger.info(f"Checking if channel #{channel_name} exists...")

        try:
            # Get existing channels from destination workspace
            dest_channels = self.dest_client.get_channels()

            # Look for existing channel
            existing_channel = None
            for channel in dest_channels:
                if channel.get("name") == channel_name:
                    existing_channel = channel
                    break

            if existing_channel:
                channel_id = existing_channel["id"]
                logger.info(f"Channel #{channel_name} already exists (ID: {channel_id})")

                # Check if bot is a member
                is_member = existing_channel.get("is_member", False)

                if not is_member and not is_private:
                    # Try to join the channel
                    logger.info(f"Bot is not in #{channel_name}, attempting to join...")
                    try:
                        self.dest_client.join_channel(channel_id)
                        logger.info(f"Successfully joined #{channel_name}")
                    except Exception as e:
                        logger.warning(f"Failed to join #{channel_name}: {e}")
                elif is_private and not is_member:
                    logger.warning(f"Channel #{channel_name} is private and bot is not a member. Manual invitation required.")

                return channel_id
            else:
                # Channel doesn't exist, create it
                logger.info(f"Creating new channel #{channel_name} (private: {is_private})")
                try:
                    response = self.dest_client.create_channel(channel_name, is_private)
                    new_channel_id = response["channel"]["id"]
                    logger.info(f"Successfully created channel #{channel_name} (ID: {new_channel_id})")

                    # Set topic and purpose if they exist
                    topic = channel_info.get("topic", {}).get("value", "")
                    purpose = channel_info.get("purpose", {}).get("value", "")

                    if topic:
                        try:
                            self.dest_client.set_channel_topic(
                                new_channel_id,
                                f"{topic} (Migrated from source workspace)"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to set topic for #{channel_name}: {e}")

                    if purpose:
                        try:
                            self.dest_client.set_channel_purpose(
                                new_channel_id,
                                f"{purpose} (Migrated from source workspace)"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to set purpose for #{channel_name}: {e}")

                    return new_channel_id

                except Exception as e:
                    logger.error(f"Failed to create channel #{channel_name}: {e}")
                    return None

        except Exception as e:
            logger.error(f"Error checking/creating channel #{channel_name}: {e}")
            return None

    def _create_user_mapping(self, source_users: List[Dict[str, Any]]):
        """Create mapping between source and destination user IDs"""
        logger.info("Creating user mapping...")

        dest_users = self.dest_client.get_users()
        dest_users_by_email = {user.get("profile", {}).get("email"): user["id"]
                              for user in dest_users
                              if user.get("profile", {}).get("email")}

        for source_user in source_users:
            source_id = source_user["id"]
            source_email = source_user.get("profile", {}).get("email")

            if source_email and source_email in dest_users_by_email:
                dest_id = dest_users_by_email[source_email]
                self.user_mapping[source_id] = dest_id
                logger.debug(f"Mapped user {source_email}: {source_id} -> {dest_id}")
            else:
                logger.warning(f"Could not map user {source_user.get('name', source_id)}")

    def _create_channels(self, source_channels: List[Dict[str, Any]]):
        """Create channels in destination workspace"""
        logger.info("Creating channels...")

        dest_channels = self.dest_client.get_channels()
        dest_channel_names = {ch["name"] for ch in dest_channels}

        for channel in tqdm(source_channels, desc="Creating channels"):
            channel_name = channel.get("name")
            if not channel_name:
                continue

            # Skip if channel already exists
            if channel_name in dest_channel_names:
                # Find the existing channel ID
                for dest_ch in dest_channels:
                    if dest_ch["name"] == channel_name:
                        self.channel_mapping[channel["id"]] = dest_ch["id"]
                        break
                logger.info(f"Channel #{channel_name} already exists, skipping creation")
                continue

            try:
                # Create the channel
                is_private = channel.get("is_private", False)
                response = self.dest_client.create_channel(channel_name, is_private)

                dest_channel_id = response["channel"]["id"]
                self.channel_mapping[channel["id"]] = dest_channel_id

                logger.info(f"Created channel #{channel_name}")

                # Set topic and purpose if they exist
                # Note: Setting topic/purpose would require additional API calls

            except Exception as e:
                logger.error(f"Failed to create channel #{channel_name}: {e}")

    def _wait_for_file_upload_completion(self, channel_id: str, file_id: str, filename: str, max_wait_time: int = 30) -> bool:
        """
        Wait for file upload to complete by checking if the file message appears in channel history
        Returns True if file message found, False if timeout
        """
        logger.info(f"Waiting for file {filename} (ID: {file_id}) to appear in channel...")

        start_time = time.time()
        check_interval = 1.0  # Check every 1 second

        while time.time() - start_time < max_wait_time:
            try:
                # Get recent channel history
                response = self.dest_client.client.conversations_history(
                    channel=channel_id,
                    limit=10,  # Check last 10 messages
                    include_all_metadata=True
                )

                if response.get("ok"):
                    messages = response.get("messages", [])

                    # Look for a message containing our uploaded file
                    for message in messages:
                        files = message.get("files", [])
                        for file_info in files:
                            if file_info.get("id") == file_id:
                                logger.info(f"File {filename} successfully posted to channel")
                                return True

                # Wait before next check
                time.sleep(check_interval)

            except Exception as e:
                logger.warning(f"Error checking channel history for file {filename}: {e}")
                time.sleep(check_interval)

        logger.warning(f"Timeout waiting for file {filename} to appear in channel after {max_wait_time}s")
        return False

    def _upload_file_for_permalink(self, local_file_path: str, file_info: Dict[str, Any]) -> Optional[str]:
        """
        Upload a file without channel parameter to get permalink
        Returns permalink if successful, None otherwise
        """
        try:
            if not Path(local_file_path).exists():
                logger.warning(f"Local file not found: {local_file_path}")
                return None

            original_filename = file_info.get("name", "unknown_file")
            file_title = file_info.get("title", original_filename)

            logger.debug(f"Uploading file {original_filename} for permalink")

            # Upload file without channel parameter to prevent immediate publishing
            with open(local_file_path, 'rb') as file_content:
                response = self.dest_client.client.files_upload_v2(
                    file=file_content,
                    filename=original_filename,
                    title=file_title
                    # Note: No channel parameter - this should keep the file private and get us a permalink
                )

            if response["ok"]:
                file_obj = response["file"]
                permalink = file_obj.get("permalink") or file_obj.get("url_private")
                if permalink:
                    logger.debug(f"Successfully got permalink for file: {original_filename}")
                    return permalink
                else:
                    logger.warning(f"No permalink in response for file: {original_filename}")
                    return None
            else:
                logger.error(f"Failed to upload file {original_filename}: {response.get('error', 'Unknown error')}")
                return None

        except Exception as e:
            logger.error(f"Error uploading file {original_filename} for permalink: {e}")
            return None

    def _format_timestamp_jst(self, slack_timestamp: str) -> str:
        """Convert Slack timestamp to JST formatted string"""
        try:
            # Slack timestamps are in Unix timestamp format with microseconds
            timestamp = float(slack_timestamp)
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            jst_dt = dt.astimezone(self.jst)
            return jst_dt.strftime("%Y/%m/%d %H:%M:%S JST")
        except Exception as e:
            logger.warning(f"Failed to format timestamp {slack_timestamp}: {e}")
            return slack_timestamp

    def _get_user_display_info(self, user_id: str, users_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get user display information for message posting"""
        for user in users_data:
            if user["id"] == user_id:
                profile = user.get("profile", {})
                return {
                    "display_name": profile.get("display_name") or profile.get("real_name") or user.get("name", f"user_{user_id}"),
                    "icon_url": profile.get("image_72") or profile.get("image_48") or profile.get("image_32"),
                    "real_name": profile.get("real_name", ""),
                }

        return {
            "display_name": f"user_{user_id}",
            "icon_url": None,
            "real_name": "",
        }

    def _upload_messages(self, messages_data: Dict[str, Any]):
        """Upload messages to destination channels with enhanced formatting"""
        logger.info("Uploading messages with user info and files...")

        # Load users data for user info lookup
        users_data = []
        users_file = self.output_dir / "users.json"
        if users_file.exists():
            try:
                with open(users_file, "r") as f:
                    users_data = json.load(f)
                logger.info(f"Loaded {len(users_data)} users for user info lookup")
            except Exception as e:
                logger.warning(f"Failed to load users data: {e}")
        else:
            logger.warning("No users data found - user names will show as user IDs")

        for source_channel_id, channel_data in messages_data.items():
            if source_channel_id not in self.channel_mapping:
                logger.warning(f"No mapping found for channel {source_channel_id}, skipping messages")
                continue

            dest_channel_id = self.channel_mapping[source_channel_id]
            messages = channel_data.get("messages", [])
            channel_name = channel_data["channel_info"].get("name", source_channel_id)

            if not messages:
                logger.info(f"No messages to upload for #{channel_name}")
                continue

            # Pre-scan to build thread broadcast mapping
            # Map: message_timestamp -> thread_info from thread_broadcast messages
            thread_broadcast_info = {}
            thread_broadcast_count = 0
            processed_broadcast_timestamps = set()

            for message in messages:
                if message.get("subtype") == "thread_broadcast":
                    msg_ts = message.get("ts")
                    thread_ts = message.get("thread_ts")
                    logger.debug(f"Found thread_broadcast message: ts={msg_ts}, thread_ts={thread_ts}")
                    if msg_ts and thread_ts:
                        if msg_ts not in processed_broadcast_timestamps:
                            thread_broadcast_info[msg_ts] = {
                                "thread_ts": thread_ts,
                                "should_broadcast": True,
                                "original_message": message  # Store the original for conversion
                            }
                            processed_broadcast_timestamps.add(msg_ts)
                            thread_broadcast_count += 1
                            logger.debug(f"Added to thread_broadcast_info: {msg_ts} -> {thread_ts}")
                        else:
                            logger.debug(f"Duplicate thread_broadcast message found for {msg_ts}, ignoring")

            if thread_broadcast_count > 0:
                logger.info(f"Found {thread_broadcast_count} unique thread broadcast messages in #{channel_name}")
                logger.debug(f"Thread broadcast info keys: {list(thread_broadcast_info.keys())}")

            # Filter and enhance messages
            filtered_messages = []
            for message in messages:
                msg_ts = message.get("ts")
                is_thread_broadcast = message.get("subtype") == "thread_broadcast"

                if is_thread_broadcast:
                    # Only keep the first occurrence of each thread_broadcast message
                    if msg_ts in thread_broadcast_info and message is thread_broadcast_info[msg_ts]["original_message"]:
                        # Convert this thread_broadcast message to a proper thread reply
                        enhanced_message = message.copy()
                        enhanced_message.pop("subtype", None)  # Remove thread_broadcast subtype
                        enhanced_message.pop("root", None)     # Remove root field (not needed)
                        enhanced_message["thread_ts"] = thread_broadcast_info[msg_ts]["thread_ts"]
                        enhanced_message["_should_broadcast"] = True
                        logger.info(f"Converting thread_broadcast message {msg_ts} to thread reply with broadcast")
                        filtered_messages.append(enhanced_message)
                    else:
                        logger.debug(f"Skipping duplicate thread_broadcast message for ts: {msg_ts}")
                else:
                    # Regular message - check if it needs enhancement
                    logger.debug(f"Processing regular message: ts={msg_ts}, text='{message.get('text', '')[:50]}...'")
                    if msg_ts in thread_broadcast_info:
                        # This should not happen since we only process thread_broadcast messages above
                        logger.warning(f"Unexpected: Regular message {msg_ts} matches thread_broadcast timestamp")
                    filtered_messages.append(message)

            # Count files to upload
            total_files = sum(len(msg.get("files", [])) for msg in filtered_messages)
            logger.info(f"Uploading {len(filtered_messages)} messages and {total_files} files to #{channel_name}")

            # Sort messages by timestamp (oldest first) to maintain chronological order
            filtered_messages.sort(key=lambda m: float(m.get("ts", 0)))

            # Track thread mappings: source_thread_ts -> dest_thread_ts
            thread_mapping = {}

            # Pre-process to identify thread parent messages that need to be included
            thread_parents_needed = set()
            for message in filtered_messages:
                thread_ts = message.get("thread_ts")
                if thread_ts:
                    thread_parents_needed.add(thread_ts)

            # Find any missing thread parents and include them
            if thread_parents_needed:
                all_messages = channel_data.get("messages", [])
                missing_parents = []

                for parent_ts in thread_parents_needed:
                    # Check if parent is already in our message list
                    parent_exists = any(msg.get("ts") == parent_ts for msg in filtered_messages)
                    if not parent_exists:
                        # Find the parent message in the full message list
                        for msg in all_messages:
                            if msg.get("ts") == parent_ts and msg.get("subtype") != "thread_broadcast":
                                missing_parents.append(msg)
                                logger.info(f"Including thread parent message for complete thread structure")
                                break

                # Add missing parents and re-sort
                if missing_parents:
                    filtered_messages.extend(missing_parents)
                    filtered_messages.sort(key=lambda m: float(m.get("ts", 0)))
                    logger.info(f"Added {len(missing_parents)} thread parent messages for complete threads")

            # Process messages in chronological order - each message completely before moving to next
            for message in tqdm(filtered_messages, desc=f"Uploading to #{channel_name}"):
                try:
                    posted_ts = self._upload_single_message_with_files(
                        dest_channel_id, message, users_data, channel_name, thread_mapping
                    )

                    # Store the mapping for any message that could be a thread parent
                    # This includes both regular messages and thread parent messages (where thread_ts == ts)
                    if posted_ts:
                        source_ts = message.get("ts")
                        if source_ts:
                            thread_mapping[source_ts] = posted_ts
                            # Debug logging for thread parent detection
                            thread_ts = message.get("thread_ts")
                            if thread_ts and thread_ts == source_ts:
                                logger.debug(f"Mapped thread parent {source_ts} -> {posted_ts}")

                except Exception as e:
                    logger.error(f"Failed to upload message: {e}")

            logger.info(f"Completed upload to #{channel_name}")

    def _upload_single_message_with_files(self, channel_id: str, message: Dict[str, Any],
                                         users_data: List[Dict[str, Any]], channel_name: str,
                                         thread_mapping: Dict[str, str]) -> Optional[str]:
        """Upload a single message with its files using permalink approach"""
        # Skip if message has no text or is a system message
        text = message.get("text", "")
        if not text or message.get("subtype") in ["channel_join", "channel_leave"]:
            return None

        # Skip thread broadcast messages entirely - they are duplicates of actual thread replies
        # The API will handle broadcasting when we post the original thread reply with reply_broadcast=True
        is_thread_broadcast = message.get("subtype") == "thread_broadcast"
        if is_thread_broadcast:
            logger.debug(f"Skipping thread broadcast message (duplicate) with ts: {message.get('ts')}")
            return None

        # Determine if this is a thread parent, thread reply, or regular message
        source_thread_ts = message.get("thread_ts")
        dest_thread_ts = None
        should_broadcast_reply = False

        # Check if this message should be broadcast (enhanced from thread_broadcast info)
        if message.get("_should_broadcast"):
            should_broadcast_reply = True
            logger.info(f"Message will be broadcast based on original thread broadcast data")

        if source_thread_ts:
            # Check if this is a parent message (thread_ts == ts)
            if source_thread_ts == message.get("ts"):
                # This is a parent message, not a reply
                logger.debug(f"Processing thread parent message: {source_thread_ts}")
                pass
            else:
                # This is a thread reply - find the parent message
                dest_thread_ts = thread_mapping.get(source_thread_ts)
                if not dest_thread_ts:
                    logger.warning(f"Could not find parent thread for message {message.get('ts')}, skipping thread reply (parent: {source_thread_ts})")
                    logger.debug(f"Available thread mappings: {list(thread_mapping.keys())}")
                    return None
                else:
                    logger.debug(f"Found thread parent mapping: {source_thread_ts} -> {dest_thread_ts}")

        # Get original user info
        source_user_id = message.get("user")
        user_info = self._get_user_display_info(source_user_id, users_data) if source_user_id else {
            "display_name": "Unknown User",
            "icon_url": None,
            "real_name": ""
        }

        # Format timestamp in JST for username
        jst_timestamp = self._format_timestamp_jst(message.get("ts", "0"))

        # Create username with timestamp
        username_with_timestamp = f"{user_info['display_name']} [{jst_timestamp}]"

        # Format text
        formatted_text = text

        posted_ts = None

        # Step 1: Upload files without channel parameter to get permalinks
        file_permalinks = []
        if "files" in message and message["files"]:
            for file_info in message["files"]:
                local_path = file_info.get("local_path")
                if local_path and file_info.get("download_status") == "success":
                    if Path(local_path).exists():
                        # Upload file without channel to get permalink
                        permalink = self._upload_file_for_permalink(local_path, file_info)
                        if permalink:
                            file_title = file_info.get("title") or file_info.get("name", "File")
                            file_permalinks.append(f"<{permalink}|{file_title}>")
                            logger.info(f"Got permalink for file {file_info.get('name', 'unknown')}")

        # Step 2: Compose message with file permalinks
        if file_permalinks:
            # Add file permalinks to the message text
            files_text = " ".join(file_permalinks)
            formatted_text = f"{formatted_text}\n{files_text}"

        # Post the message with text and file permalinks
        try:
            # Post the message with user info and proper threading/broadcasting
            response = self.dest_client.post_message(
                channel_id=channel_id,
                text=formatted_text,
                username=username_with_timestamp,
                icon_url=user_info["icon_url"],
                thread_ts=dest_thread_ts,  # This will be None for main messages, set for thread replies
                reply_broadcast=should_broadcast_reply  # Enable broadcast for original thread broadcast messages
            )

            # Add small delay between messages to avoid rate limits
            time.sleep(0.5)

            # Add reactions if present in original message
            if response.get("ok") and response.get("ts"):
                posted_ts = response["ts"]
                self._add_message_reactions(channel_id, posted_ts, message, channel_name)

        except Exception as e:
            logger.error(f"Failed to post message: {e}")

        return posted_ts

    def _add_message_reactions(self, channel_id: str, message_ts: str, original_message: Dict[str, Any], channel_name: str):
        """Add reactions to a posted message based on the original message reactions"""
        reactions = original_message.get("reactions", [])
        if not reactions:
            return

        logger.debug(f"Adding {len(reactions)} reaction types to message in #{channel_name}")

        successful_reactions = 0
        skipped_reactions = 0

        for reaction in reactions:
            emoji_name = reaction.get("name")
            if not emoji_name:
                continue

            try:
                # Add the reaction from the bot
                self.dest_client.add_reaction(
                    channel_id=channel_id,
                    message_ts=message_ts,
                    emoji_name=emoji_name
                )
                logger.debug(f"Added reaction :{emoji_name}: to message")
                successful_reactions += 1

                # Small delay between reactions to avoid rate limits
                time.sleep(0.2)

            except Exception as e:
                error_str = str(e).lower()

                # Categorize different types of errors for better user feedback
                if "invalid_name" in error_str or "no_reaction" in error_str:
                    logger.debug(f"Skipped reaction :{emoji_name}: (emoji does not exist in destination workspace)")
                elif "already_reacted" in error_str:
                    logger.debug(f"Skipped reaction :{emoji_name}: (already exists on message)")
                elif "invalid_auth" in error_str or "not_authed" in error_str:
                    logger.warning(f"Authentication error adding reaction :{emoji_name}: - check bot permissions")
                elif "channel_not_found" in error_str:
                    logger.warning(f"Channel access error adding reaction :{emoji_name}:")
                else:
                    logger.debug(f"Failed to add reaction :{emoji_name}: {e}")

                skipped_reactions += 1
                continue

        # Summary logging
        if successful_reactions > 0 or skipped_reactions > 0:
            if skipped_reactions == 0:
                logger.debug(f"Successfully added all {successful_reactions} reactions to message in #{channel_name}")
            else:
                logger.debug(f"Added {successful_reactions} reactions, skipped {skipped_reactions} reactions for message in #{channel_name}")

    def _test_channel_access(self, channel: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test comprehensive access to a channel and return detailed diagnostic information
        """
        channel_id = channel["id"]
        channel_name = channel.get("name", channel_id)
        is_private = channel.get("is_private", False)
        is_member = channel.get("is_member", False)

        diagnostic = {
            "channel_name": channel_name,
            "channel_id": channel_id,
            "is_private": is_private,
            "is_member": is_member,
            "tests": {},
            "success": False,
            "error_details": None
        }

        # Test 1: Basic channel info access
        try:
            info_response = self.source_client.get_channel_info(channel_id)
            diagnostic["tests"]["channel_info"] = {
                "success": True,
                "details": "Successfully retrieved channel information"
            }
        except Exception as e:
            diagnostic["tests"]["channel_info"] = {
                "success": False,
                "error": str(e),
                "details": "Failed to retrieve channel information"
            }

        # Test 2: Message history access (try to fetch just 1 message)
        try:
            response = self.source_client._make_request(
                "conversations_history",
                channel=channel_id,
                limit=1
            )
            message_count = len(response.get("messages", []))
            diagnostic["tests"]["message_access"] = {
                "success": True,
                "details": f"Successfully accessed message history. Found {message_count} messages in sample"
            }
            diagnostic["success"] = True
        except Exception as e:
            error_str = str(e)
            diagnostic["tests"]["message_access"] = {
                "success": False,
                "error": error_str,
                "details": "Failed to access message history"
            }
            diagnostic["error_details"] = error_str

            # Check for common error patterns
            if "not_in_channel" in error_str:
                diagnostic["diagnosis"] = "Bot is not a member of this private channel"
                diagnostic["solution"] = "Manually add the bot to the private channel"
            elif "missing_scope" in error_str:
                diagnostic["diagnosis"] = "Bot lacks required scopes for private channels"
                diagnostic["solution"] = "Add 'groups:read' and 'groups:history' scopes to your Slack app"
            elif "channel_not_found" in error_str:
                diagnostic["diagnosis"] = "Channel not found or no access"
                diagnostic["solution"] = "Verify channel exists and bot has proper permissions"
            elif "access_denied" in error_str or "forbidden" in error_str:
                diagnostic["diagnosis"] = "Access denied to channel"
                diagnostic["solution"] = "Check bot permissions and workspace admin settings"

        # Test 3: Bot membership verification for private channels
        if is_private and is_member:
            try:
                # Try to get channel members to verify bot is really a member
                members_response = self.source_client._make_request(
                    "conversations_members",
                    channel=channel_id,
                    limit=10
                )
                members = members_response.get("members", [])
                # Get bot user ID
                auth_response = self.source_client._make_request("auth_test")
                bot_user_id = auth_response.get("user_id")

                is_really_member = bot_user_id in members
                diagnostic["tests"]["membership_verification"] = {
                    "success": True,
                    "details": f"Bot membership verified: {is_really_member}",
                    "bot_user_id": bot_user_id,
                    "is_really_member": is_really_member
                }

                if not is_really_member:
                    diagnostic["diagnosis"] = "Channel metadata says bot is member, but bot is not in member list"
                    diagnostic["solution"] = "Re-add bot to the channel or check for sync issues"

            except Exception as e:
                diagnostic["tests"]["membership_verification"] = {
                    "success": False,
                    "error": str(e),
                    "details": "Could not verify bot membership"
                }

        return diagnostic

    def diagnose_channel_access(self, channel_name: str) -> None:
        """
        Run comprehensive diagnostics on a specific channel to identify access issues
        """
        logger.info(f"🔍 Running diagnostics for channel #{channel_name}...")

        # Get all channels to find the target channel
        try:
            all_channels = self.source_client.get_channels()
        except Exception as e:
            logger.error(f"Failed to get channels list: {e}")
            return

        target_channel = None
        for channel in all_channels:
            if channel.get("name") == channel_name:
                target_channel = channel
                break

        if not target_channel:
            logger.error(f"❌ Channel #{channel_name} not found")
            return

        # Run comprehensive tests
        diagnostic = self._test_channel_access(target_channel)

        # Print diagnostic results
        logger.info(f"📊 Diagnostic Results for #{channel_name}:")
        logger.info(f"   Channel ID: {diagnostic['channel_id']}")
        logger.info(f"   Private: {diagnostic['is_private']}")
        logger.info(f"   Bot is member: {diagnostic['is_member']}")
        logger.info(f"   Overall Success: {diagnostic['success']}")

        for test_name, test_result in diagnostic['tests'].items():
            status = "✅" if test_result['success'] else "❌"
            logger.info(f"   {status} {test_name}: {test_result['details']}")
            if not test_result['success'] and 'error' in test_result:
                logger.info(f"      Error: {test_result['error']}")

        if diagnostic.get('diagnosis'):
            logger.warning(f"🔍 Diagnosis: {diagnostic['diagnosis']}")
            logger.info(f"💡 Suggested Solution: {diagnostic['solution']}")

        if not diagnostic['success']:
            logger.error(f"❌ Channel #{channel_name} is not accessible for download")
        else:
            logger.info(f"✅ Channel #{channel_name} appears accessible for download")

    def migrate(self, download_only: bool = False, upload_only: bool = False):
        """Run the complete migration process"""
        if upload_only:
            self.upload_workspace_data()
        elif download_only:
            self.download_workspace_data()
        else:
            data = self.download_workspace_data()
            self.upload_workspace_data(data)

    def _auto_join_channel(self, channel_id: str, channel_name: str, is_private: bool = False) -> bool:
        """
        Automatically join a channel to enable message downloading

        Args:
            channel_id: Channel ID to join
            channel_name: Channel name for logging
            is_private: Whether this is a private channel

        Returns:
            bool: True if successfully joined or already member, False otherwise
        """
        try:
            if is_private:
                # For private channels, we can't auto-join - need to be invited
                logger.warning(f"Cannot auto-join private channel #{channel_name}. Bot must be manually invited.")
                return False

            # Try to join public channel
            response = self.source_client._make_request("conversations_join", channel=channel_id)

            if response.get("ok"):
                logger.info(f"✅ Successfully joined channel #{channel_name}")
                return True
            else:
                error = response.get("error", "unknown_error")
                if error == "is_already_in_channel":
                    logger.info(f"✅ Already member of channel #{channel_name}")
                    return True
                else:
                    logger.error(f"❌ Failed to join #{channel_name}: {error}")
                    return False

        except Exception as e:
            logger.error(f"❌ Exception joining #{channel_name}: {e}")
            return False

    def _handle_not_in_channel_error(self, channel: Dict[str, Any]) -> bool:
        """
        Handle 'not_in_channel' error by attempting to join the channel

        Args:
            channel: Channel dictionary with id, name, is_private info

        Returns:
            bool: True if resolved (joined successfully), False otherwise
        """
        channel_id = channel["id"]
        channel_name = channel.get("name", channel_id)
        is_private = channel.get("is_private", False)

        logger.info(f"🔄 Bot is not a member of #{channel_name}. Attempting to resolve...")

        if is_private:
            logger.warning(f"❌ Cannot access private channel #{channel_name}")
            logger.warning(f"   Solution: Manually invite the bot to the private channel:")
            logger.warning(f"   1. Go to #{channel_name} in Slack")
            logger.warning(f"   2. Type: /invite @YourBotName")
            logger.warning(f"   3. Then re-run the download command")
            return False
        else:
            # Try to auto-join public channel
            return self._auto_join_channel(channel_id, channel_name, is_private)
