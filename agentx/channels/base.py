"""Base channel interface for chat platforms."""

from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable

from loguru import logger

from agentx.bus.events import InboundMessage, OutboundMessage
from agentx.bus.queue import MessageBus


class BaseChannel(ABC):
    """
    Abstract base class for chat channel implementations.
    
    Each channel (Telegram, Discord, etc.) should implement this interface
    to integrate with the agentx message bus.
    """
    
    name: str = "base"
    
    def __init__(self, config: Any, bus: MessageBus):
        """
        Initialize the channel.
        
        Args:
            config: Channel-specific configuration.
            bus: The message bus for communication.
        """
        self.config = config
        self.bus = bus
        self._running = False
        self._on_inbound: Callable[[str, str], Awaitable[None]] | None = None  # Optional callback (channel, chat_id)
        self._send_thinking_cb: Callable[[str, str], Awaitable[None]] | None = None  # Callback to send thinking
    
    def set_inbound_callback(self, callback: Callable[[str, str], Awaitable[None]]) -> None:
        """Set callback to be called when inbound message is handled."""
        self._on_inbound = callback
    
    async def send_thinking(self, chat_id: str) -> None:
        """Send 'Thinking...' message to the chat."""
        logger.info(f"DEBUG: send_thinking called for chat_id={chat_id}, cb={self._send_thinking_cb}")
        if self._send_thinking_cb:
            await self._send_thinking_cb(self.name, chat_id)
    
    @abstractmethod
    async def start(self) -> None:
        """
        Start the channel and begin listening for messages.
        
        This should be a long-running async task that:
        1. Connects to the chat platform
        2. Listens for incoming messages
        3. Forwards messages to the bus via _handle_message()
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and clean up resources."""
        pass
    
    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        Send a message through this channel.
        
        Args:
            msg: The message to send.
        """
        pass
    
    def is_allowed(self, sender_id: str) -> bool:
        """
        Check if a sender is allowed to use this bot.
        
        Args:
            sender_id: The sender's identifier.
        
        Returns:
            True if allowed, False otherwise.
        """
        allow_list = getattr(self.config, "allow_from", [])
        
        # If no allow list, allow everyone
        if not allow_list:
            return True
        
        sender_str = str(sender_id)
        if sender_str in allow_list:
            return True
        if "|" in sender_str:
            for part in sender_str.split("|"):
                if part and part in allow_list:
                    return True
        return False
    
    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """
        Handle an incoming message from the chat platform.
        
        This method checks permissions and forwards to the bus.
        
        Args:
            sender_id: The sender's identifier.
            chat_id: The chat/channel identifier.
            content: Message text content.
            media: Optional list of media URLs.
            metadata: Optional channel-specific metadata.
            session_key: Optional session key override (e.g. thread-scoped sessions).
        """
        if not self.is_allowed(sender_id):
            logger.warning(
                "Access denied for sender {} on channel {}. "
                "Add them to allowFrom list in config to grant access.",
                sender_id, self.name,
            )
            return
        
        # Send "Thinking..." immediately when message is received
        logger.info(f"DEBUG: handle_message called for sender={sender_id}, chat_id={chat_id}")
        await self.send_thinking(str(chat_id))
        
        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
            session_key_override=session_key,
        )
        
        await self.bus.publish_inbound(msg)
        
        # Call inbound callback if set (e.g., to clear thinking state)
        if self._on_inbound:
            await self._on_inbound(self.name, str(chat_id))
    
    @property
    def is_running(self) -> bool:
        """Check if the channel is running."""
        return self._running
