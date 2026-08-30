from functools import lru_cache

from travel_ai_concierge.conversation.store import ConversationStore, Turn

__all__ = ["ConversationStore", "Turn", "get_conversation_store"]


@lru_cache(maxsize=1)
def get_conversation_store() -> ConversationStore:
    return ConversationStore()
