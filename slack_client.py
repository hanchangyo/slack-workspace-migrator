import time
import logging
from typing import List, Dict, Any, Optional, Callable
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Rate limit tiers based on Slack API documentation
# https://api.slack.com/apis/rate-limits
API_RATE_LIMITS = {
    # conversations.history is Tier 3 (50+/min) for Marketplace apps
    # but Tier 1 (1+/min) for non-Marketplace apps created after May 29, 2025
    "conversations_history": 1.2,  # 1 request per minute + small buffer
    "conversations_replies": 1.2,  # Same tier as conversations_history
    "conversations_list": 3.0,     # Tier 2 (20+/min)
    "users_list": 3.0,             # Tier 2 (20+/min)
    "team_info": 60.0,             # Tier 1 (1+/min)
    "conversations_info": 3.0,     # Tier 2 (20+/min)
    "conversations_create": 3.0,   # Tier 2 (20+/min)
    "conversations_invite": 3.0,   # Tier 2 (20+/min)
    "chat_postMessage": 1.0,       # Special tier (1/sec per channel)
}

class SlackClient:
    """Wrapper for Slack WebClient with error handling and rate limiting"""

    def __init__(self, token: str, rate_limit_delay: float = 1.0, max_retries: int = 3):
        self.client = WebClient(token=token)
        self.base_rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries

    def _get_method_delay(self, method: str) -> float:
        """Get the appropriate delay for a specific API method"""
        return API_RATE_LIMITS.get(method, self.base_rate_limit_delay)

    def _make_request(self, method: str, **kwargs) -> Dict[str, Any]:
        """Make API request with retry logic and rate limiting"""
        method_delay = self._get_method_delay(method)

        for attempt in range(self.max_retries):
            try:
                # Apply method-specific rate limiting
                time.sleep(method_delay)
                response = getattr(self.client, method)(**kwargs)
                return response.data
            except SlackApiError as e:
                error_code = e.response["error"]

                if error_code in ["rate_limited", "ratelimited"]:
                    # Get the retry-after header or use a default long delay
                    retry_after = int(e.response.get("headers", {}).get("Retry-After", 60))
                    logger.warning(f"Rate limited on {method}, waiting {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue
                elif method == "reactions_add" and error_code in ["invalid_name", "no_reaction"]:
                    # Don't retry for emoji validation errors - they won't be resolved by retrying
                    logger.debug(f"Emoji validation error for {method}: {error_code}")
                    raise
                elif error_code in ["invalid_auth", "account_inactive", "token_revoked", "not_authed"]:
                    # Don't retry for authentication errors
                    logger.error(f"Authentication error for {method}: {error_code}")
                    raise
                elif attempt == self.max_retries - 1:
                    logger.error(f"API call {method} failed after {self.max_retries} attempts: {e}")
                    raise
                else:
                    logger.warning(f"API call {method} failed, retrying... (attempt {attempt + 1}/{self.max_retries})")
                    # Exponential backoff for other errors
                    time.sleep(2 ** attempt)

        raise Exception(f"Failed to make request {method} after {self.max_retries} attempts")

    def get_channels(self, exclude_archived: bool = True) -> List[Dict[str, Any]]:
        """Get all channels from workspace"""
        channels = []
        cursor = None

        while True:
            response = self._make_request(
                "conversations_list",
                exclude_archived=exclude_archived,
                limit=200,  # Use pagination as recommended
                cursor=cursor
            )

            channels.extend(response["channels"])

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return channels

    def get_users(self) -> List[Dict[str, Any]]:
        """Get all users from workspace"""
        users = []
        cursor = None

        while True:
            response = self._make_request(
                "users_list",
                limit=200,  # Use pagination as recommended
                cursor=cursor
            )

            users.extend(response["members"])

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return users

    def get_channel_messages(self, channel_id: str, oldest: Optional[str] = None, include_thread_replies: bool = True,
                           progress_callback: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """Get all messages from a channel, optionally including thread replies

        Args:
            channel_id: Channel ID to fetch messages from
            oldest: Oldest timestamp to fetch messages from
            include_thread_replies: Whether to include thread replies
            progress_callback: Optional callback function(messages_batch) called after each batch is fetched
        """
        messages = []
        cursor = None

        with tqdm(desc=f"Fetching messages from {channel_id}") as pbar:
            while True:
                kwargs = {
                    "channel": channel_id,
                    "limit": 15,  # New limit for non-Marketplace apps per Slack documentation
                    "cursor": cursor
                }
                if oldest:
                    kwargs["oldest"] = oldest

                response = self._make_request("conversations_history", **kwargs)

                batch_messages = response["messages"]
                messages.extend(batch_messages)
                pbar.update(len(batch_messages))

                # Call progress callback if provided
                if progress_callback and batch_messages:
                    try:
                        progress_callback(batch_messages)
                    except Exception as e:
                        logger.warning(f"Progress callback failed: {e}")

                cursor = response.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

        # If requested, fetch thread replies for messages that have them
        if include_thread_replies:
            messages_with_replies = []
            thread_count = 0

            for message in messages:
                messages_with_replies.append(message)

                # Check if this message has thread replies
                if message.get("reply_count", 0) > 0:
                    thread_ts = message.get("ts")
                    if thread_ts:
                        thread_count += 1
                        logger.info(f"Fetching {message.get('reply_count')} replies for thread {thread_ts}")
                        thread_replies = self.get_thread_replies(channel_id, thread_ts)
                        # Add thread replies after the parent message
                        messages_with_replies.extend(thread_replies)

                        # Call progress callback for thread replies too
                        if progress_callback and thread_replies:
                            try:
                                progress_callback(thread_replies)
                            except Exception as e:
                                logger.warning(f"Progress callback failed for thread replies: {e}")

            if thread_count > 0:
                logger.info(f"Downloaded replies from {thread_count} threads")

            return messages_with_replies

        return messages

    def get_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict[str, Any]]:
        """Get all replies in a specific thread"""
        replies = []
        cursor = None

        while True:
            response = self._make_request(
                "conversations_replies",
                channel=channel_id,
                ts=thread_ts,
                cursor=cursor
            )

            batch_replies = response["messages"]
            # Skip the first message (parent) since we already have it
            if batch_replies and len(batch_replies) > 1:
                replies.extend(batch_replies[1:])  # Skip parent message
            elif batch_replies and cursor is None:
                # First request, skip parent if it's the only message
                if len(batch_replies) > 1:
                    replies.extend(batch_replies[1:])

            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return replies

    def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """Get channel information"""
        return self._make_request("conversations_info", channel=channel_id)

    def create_channel(self, name: str, is_private: bool = False) -> Dict[str, Any]:
        """Create a new channel"""
        return self._make_request("conversations_create", name=name, is_private=is_private)

    def invite_users_to_channel(self, channel_id: str, user_ids: List[str]) -> Dict[str, Any]:
        """Invite users to a channel"""
        return self._make_request("conversations_invite", channel=channel_id, users=",".join(user_ids))

    def join_channel(self, channel_id: str) -> Dict[str, Any]:
        """Join a channel"""
        return self._make_request("conversations_join", channel=channel_id)

    def set_channel_topic(self, channel_id: str, topic: str) -> Dict[str, Any]:
        """Set channel topic"""
        return self._make_request("conversations_setTopic", channel=channel_id, topic=topic)

    def set_channel_purpose(self, channel_id: str, purpose: str) -> Dict[str, Any]:
        """Set channel purpose"""
        return self._make_request("conversations_setPurpose", channel=channel_id, purpose=purpose)

    def post_message(self, channel_id: str, text: str, username: Optional[str] = None,
                    icon_url: Optional[str] = None, thread_ts: Optional[str] = None,
                    reply_broadcast: bool = False) -> Dict[str, Any]:
        """
        Post a message to a channel

        Args:
            channel_id: Channel to post to
            text: Message text
            username: Username to display as (for bot messages)
            icon_url: Icon URL for the username
            thread_ts: Timestamp of parent message (for thread replies)
            reply_broadcast: If True, broadcast thread reply to channel (like "also send to channel")
        """
        kwargs = {
            "channel": channel_id,
            "text": text
        }

        if username:
            kwargs["username"] = username
        if icon_url:
            kwargs["icon_url"] = icon_url
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
            # Only add reply_broadcast if this is actually a thread reply
            if reply_broadcast:
                kwargs["reply_broadcast"] = True

        return self._make_request("chat_postMessage", **kwargs)

    def upload_file(self, file_path: str, channel_id: str,
                    initial_comment: Optional[str] = None,
                    thread_ts: Optional[str] = None,
                    filename: Optional[str] = None,
                    title: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a file to a channel.
        Uses files_upload_v2 method from slack_sdk.
        """
        for attempt in range(self.max_retries):
            try:
                # files_upload_v2 needs a file-like object
                with open(file_path, 'rb') as file_content:
                    kwargs = {
                        "channel": channel_id,
                        "file": file_content,
                    }
                    if initial_comment:
                        kwargs["initial_comment"] = initial_comment
                    if thread_ts:
                        kwargs["thread_ts"] = thread_ts
                    if filename:
                        kwargs["filename"] = filename
                    if title:
                        kwargs["title"] = title

                    # Use a longer delay for file uploads as they can be slow
                    time.sleep(max(self.base_rate_limit_delay, 1.0))
                    response = self.client.files_upload_v2(**kwargs)
                    return response.data

            except SlackApiError as e:
                error_code = e.response["error"]
                if error_code in ["rate_limited", "ratelimited"]:
                    retry_after = int(e.response.get("headers", {}).get("Retry-After", 60))
                    logger.warning(f"Rate limited on file upload, waiting {retry_after} seconds...")
                    time.sleep(retry_after)
                    continue
                elif attempt == self.max_retries - 1:
                    logger.error(f"File upload failed after {self.max_retries} attempts: {e}")
                    raise
                else:
                    logger.warning(f"File upload failed, retrying... (attempt {attempt + 1}/{self.max_retries})")
                    time.sleep(2 ** attempt)
            except FileNotFoundError:
                logger.error(f"File not found at path: {file_path}")
                # Don't retry if file is not found
                raise

        raise Exception(f"Failed to upload file {file_path} after {self.max_retries} attempts")

    def get_workspace_info(self) -> Dict[str, Any]:
        """Get workspace information"""
        return self._make_request("team_info")

    def add_reaction(self, channel_id: str, message_ts: str, emoji_name: str) -> Dict[str, Any]:
        """Add a reaction to a message"""
        return self._make_request("reactions_add",
                                channel=channel_id,
                                timestamp=message_ts,
                                name=emoji_name)

    def get_channel_message_count_estimate(self, channel_id: str) -> Optional[int]:
        """
        Attempt to estimate message count for a channel using various API approaches
        Returns None if unable to determine
        """
        try:
            # Approach 1: Try getting conversations.history with limit=1 to check if response metadata gives us total
            response = self._make_request(
                "conversations_history",
                channel=channel_id,
                limit=1,
                include_all_metadata=True
            )

            # Check if response metadata contains total count info
            metadata = response.get("response_metadata", {})
            if "total_count" in metadata:
                return metadata["total_count"]

            # Approach 2: Check if the single message response gives us position info
            messages = response.get("messages", [])
            if messages and len(messages) == 1:
                # Some APIs include position/index info in messages
                message = messages[0]
                if "message_count" in message or "index" in message:
                    return message.get("message_count") or message.get("index")

            # Approach 3: Try conversations.info to see if it has extended metadata
            info_response = self._make_request("conversations_info", channel=channel_id, include_num_members=True)
            channel_info = info_response.get("channel", {})

            # Check for any count-related fields
            count_fields = ["message_count", "num_messages", "total_messages", "messages_count"]
            for field in count_fields:
                if field in channel_info:
                    return channel_info[field]

            # If no direct method works, we can't estimate without downloading all messages
            return None

        except Exception as e:
            logger.warning(f"Failed to estimate message count for channel {channel_id}: {e}")
            return None

    def get_channels_with_message_estimates(self, exclude_archived: bool = True) -> List[Dict[str, Any]]:
        """Get all channels with estimated message counts where possible"""
        channels = self.get_channels(exclude_archived)

        logger.info(f"Attempting to estimate message counts for {len(channels)} channels...")

        for channel in channels:
            channel_id = channel["id"]
            channel_name = channel.get("name", channel_id)

            # Only try for channels we can access
            if not channel.get("is_member", False) and channel.get("is_private", False):
                logger.debug(f"Skipping private channel #{channel_name} (not a member)")
                continue

            estimated_count = self.get_channel_message_count_estimate(channel_id)
            if estimated_count is not None:
                channel["estimated_message_count"] = estimated_count
                logger.info(f"#{channel_name}: ~{estimated_count} messages")
            else:
                logger.debug(f"#{channel_name}: Could not estimate message count")

        return channels
