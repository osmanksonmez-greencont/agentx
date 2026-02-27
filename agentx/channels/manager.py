"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from loguru import logger

from agentx.bus.events import OutboundMessage
from agentx.bus.queue import MessageBus
from agentx.channels.base import BaseChannel
from agentx.config.schema import Config

# Team queue monitoring
TEAM_QUEUE_DB = os.path.expanduser("~/.agentx/data/team/queue.db")
TEAM_NOTIF_LAST_ID_FILE = os.path.expanduser("~/.agentx/data/team/last_notif_id.txt")


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.
    
    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages
    """
    
    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._thinking_sent: set[str] = set()  # Track chat_ids that received thinking message
        self._team_monitor_task: asyncio.Task | None = None
        
        self._init_channels()
    
    def _init_channels(self) -> None:
        """Initialize channels based on config."""
        
        # Callback to clear thinking state when new message arrives
        async def clear_thinking_cb(channel: str, chat_id: str):
            self.clear_thinking(channel, chat_id)
        
        # Callback to send thinking message
        async def send_thinking_cb(channel: str, chat_id: str) -> None:
            logger.info(f"DEBUG: send_thinking_cb called for channel={channel}, chat_id={chat_id}")
            if not self.config.channels.send_thinking:
                logger.info("DEBUG: send_thinking disabled in config")
                return
            chat_key = f"{channel}:{chat_id}"
            if chat_key in self._thinking_sent:
                logger.info(f"DEBUG: thinking already sent for {chat_key}")
                return  # Already sent
            self._thinking_sent.add(chat_key)
            ch = self.channels.get(channel)
            if ch:
                try:
                    await ch.send_thinking(chat_id)
                except Exception as e:
                    logger.error("Error sending thinking on {}: {}", channel, e)
        
        # Telegram channel
        if self.config.channels.telegram.enabled:
            try:
                from agentx.channels.telegram import TelegramChannel
                self.channels["telegram"] = TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    groq_api_key=self.config.providers.groq.api_key,
                )
                self.channels["telegram"].set_inbound_callback(clear_thinking_cb)
                self.channels["telegram"]._send_thinking_cb = send_thinking_cb
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning("Telegram channel not available: {}", e)
        
        # WhatsApp channel
        if self.config.channels.whatsapp.enabled:
            try:
                from agentx.channels.whatsapp import WhatsAppChannel
                self.channels["whatsapp"] = WhatsAppChannel(
                    self.config.channels.whatsapp, self.bus
                )
                self.channels["whatsapp"].set_inbound_callback(clear_thinking_cb)
                self.channels["whatsapp"]._send_thinking_cb = send_thinking_cb
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                logger.warning("WhatsApp channel not available: {}", e)

        # Discord channel
        if self.config.channels.discord.enabled:
            try:
                from agentx.channels.discord import DiscordChannel
                self.channels["discord"] = DiscordChannel(
                    self.config.channels.discord, self.bus
                )
                self.channels["discord"].set_inbound_callback(clear_thinking_cb)
                self.channels["discord"]._send_thinking_cb = send_thinking_cb
                logger.info("Discord channel enabled")
            except ImportError as e:
                logger.warning("Discord channel not available: {}", e)
        
        # Feishu channel
        if self.config.channels.feishu.enabled:
            try:
                from agentx.channels.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(
                    self.config.channels.feishu, self.bus
                )
                self.channels["feishu"].set_inbound_callback(clear_thinking_cb)
                self.channels["feishu"]._send_thinking_cb = send_thinking_cb
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning("Feishu channel not available: {}", e)

        # Mochat channel
        if self.config.channels.mochat.enabled:
            try:
                from agentx.channels.mochat import MochatChannel

                self.channels["mochat"] = MochatChannel(
                    self.config.channels.mochat, self.bus
                )
                self.channels["mochat"].set_inbound_callback(clear_thinking_cb)
                self.channels["mochat"]._send_thinking_cb = send_thinking_cb
                logger.info("Mochat channel enabled")
            except ImportError as e:
                logger.warning("Mochat channel not available: {}", e)

        # DingTalk channel
        if self.config.channels.dingtalk.enabled:
            try:
                from agentx.channels.dingtalk import DingTalkChannel
                self.channels["dingtalk"] = DingTalkChannel(
                    self.config.channels.dingtalk, self.bus
                )
                self.channels["dingtalk"].set_inbound_callback(clear_thinking_cb)
                self.channels["dingtalk"]._send_thinking_cb = send_thinking_cb
                logger.info("DingTalk channel enabled")
            except ImportError as e:
                logger.warning("DingTalk channel not available: {}", e)

        # Email channel
        if self.config.channels.email.enabled:
            try:
                from agentx.channels.email import EmailChannel
                self.channels["email"] = EmailChannel(
                    self.config.channels.email, self.bus
                )
                self.channels["email"].set_inbound_callback(clear_thinking_cb)
                self.channels["email"]._send_thinking_cb = send_thinking_cb
                logger.info("Email channel enabled")
            except ImportError as e:
                logger.warning("Email channel not available: {}", e)

        # Slack channel
        if self.config.channels.slack.enabled:
            try:
                from agentx.channels.slack import SlackChannel
                self.channels["slack"] = SlackChannel(
                    self.config.channels.slack, self.bus
                )
                self.channels["slack"].set_inbound_callback(clear_thinking_cb)
                self.channels["slack"]._send_thinking_cb = send_thinking_cb
                logger.info("Slack channel enabled")
            except ImportError as e:
                logger.warning("Slack channel not available: {}", e)

        # QQ channel
        if self.config.channels.qq.enabled:
            try:
                from agentx.channels.qq import QQChannel
                self.channels["qq"] = QQChannel(
                    self.config.channels.qq,
                    self.bus,
                )
                self.channels["qq"].set_inbound_callback(clear_thinking_cb)
                self.channels["qq"]._send_thinking_cb = send_thinking_cb
                logger.info("QQ channel enabled")
            except ImportError as e:
                logger.warning("QQ channel not available: {}", e)
    
    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error("Failed to start channel {}: {}", name, e)

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return
        
        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())
        
        # Start team queue monitor
        self._team_monitor_task = asyncio.create_task(self._monitor_team_queue())
        
        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            logger.info("Starting {} channel...", name)
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))
        
        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
        logger.info("Stopping all channels...")
        
        # Stop team monitor
        if self._team_monitor_task:
            self._team_monitor_task.cancel()
            try:
                await self._team_monitor_task
            except asyncio.CancelledError:
                pass
        
        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        
        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Stopped {} channel", name)
            except Exception as e:
                logger.error("Error stopping {}: {}", name, e)
    
    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")
        
        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )
                
                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not self.config.channels.send_tool_hints:
                        continue
                    if not msg.metadata.get("_tool_hint") and not self.config.channels.send_progress:
                        continue
                
                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error("Error sending to {}: {}", msg.channel, e)
                else:
                    logger.warning("Unknown channel: {}", msg.channel)
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
    
    def clear_thinking(self, channel: str, chat_id: str) -> None:
        """Clear thinking state for a chat (call when new inbound message arrives)."""
        chat_key = f"{channel}:{chat_id}"
        self._thinking_sent.discard(chat_key)
    
    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)
    
    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running
            }
            for name, channel in self.channels.items()
        }
    
    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
    
    # === Team Queue Monitoring ===
    
    def _get_last_notif_id(self) -> int:
        """Get the last notified event ID."""
        try:
            if os.path.exists(TEAM_NOTIF_LAST_ID_FILE):
                with open(TEAM_NOTIF_LAST_ID_FILE) as f:
                    return int(f.read().strip())
        except:
            pass
        return 0
    
    def _set_last_notif_id(self, event_id: int) -> None:
        """Save the last notified event ID."""
        os.makedirs(os.path.dirname(TEAM_NOTIF_LAST_ID_FILE), exist_ok=True)
        with open(TEAM_NOTIF_LAST_ID_FILE, "w") as f:
            f.write(str(event_id))
    
    def _get_latest_event_id(self) -> int:
        """Get the latest event ID from the team queue."""
        try:
            if not os.path.exists(TEAM_QUEUE_DB):
                return 0
            conn = sqlite3.connect(TEAM_QUEUE_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(id) FROM queue_messages WHERE queue_name = 'team.task.events'")
            result = cursor.fetchone()
            conn.close()
            return result[0] if result and result[0] else 0
        except Exception as e:
            logger.debug("Error getting latest event ID: {}", e)
            return 0
    
    def _get_latest_event(self) -> dict | None:
        """Get the latest team task event."""
        try:
            if not os.path.exists(TEAM_QUEUE_DB):
                return None
            conn = sqlite3.connect(TEAM_QUEUE_DB)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT payload_json FROM queue_messages 
                WHERE queue_name = 'team.task.events'
                ORDER BY id DESC LIMIT 1
            """)
            result = cursor.fetchone()
            conn.close()
            if result:
                return json.loads(result[0])
        except Exception as e:
            logger.debug("Error getting latest event: {}", e)
        return None
    
    async def _monitor_team_queue(self) -> None:
        """Monitor team queue for task completion events."""
        logger.info("Team queue monitor started")
        
        # Initialize last notified ID
        last_id = self._get_last_notif_id()
        current_id = self._get_latest_event_id()
        if current_id > last_id:
            last_id = current_id
            self._set_last_notif_id(last_id)
        
        while True:
            try:
                await asyncio.sleep(2)  # Check every 2 seconds
                
                current_id = self._get_latest_event_id()
                if current_id > last_id:
                    last_id = current_id
                    self._set_last_notif_id(last_id)
                    
                    # Get the latest event
                    event = self._get_latest_event()
                    if not event:
                        continue
                    
                    kind = event.get("kind")
                    message = event.get("message", "")
                    
                    # Send notification for completed tasks
                    if kind == "task_completed":
                        notif_msg = f"✓ Görev tamamlandı: {message}"
                        logger.info("Team notification: {}", notif_msg)
                        await self._send_team_notification(notif_msg)
                    elif kind == "goal_completed":
                        notif_msg = "🎉 Tüm proje işleri tamamlandı!"
                        logger.info("Team notification: {}", notif_msg)
                        await self._send_team_notification(notif_msg)
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in team queue monitor: {}", e)
    
    async def _send_team_notification(self, message: str) -> None:
        """Send team notification to Telegram."""
        telegram = self.channels.get("telegram")
        if not telegram or not telegram.is_running:
            logger.debug("Telegram not available for notification")
            return
        
        # Get the configured chat ID from config
        chat_id = None
        if self.config.channels.telegram.allowFrom:
            chat_id = self.config.channels.telegram.allowFrom[0]
        
        if not chat_id:
            logger.warning("No Telegram chat ID configured for notifications")
            return
        
        try:
            outbound = OutboundMessage(
                channel="telegram",
                chat_id=chat_id,
                content=message,
            )
            await telegram.send(outbound)
        except Exception as e:
            logger.error("Failed to send team notification: {}", e)
