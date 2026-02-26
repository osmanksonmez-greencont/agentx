"""Message bus module for decoupled channel-agent communication."""

from agentx.bus.events import InboundMessage, OutboundMessage
from agentx.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
