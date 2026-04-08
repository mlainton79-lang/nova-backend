from abc import ABC, abstractmethod
from typing import List
from app.schemas.chat import HistoryMessage

class ProviderAdapter(ABC):
    @abstractmethod
    async def chat(self, message: str, history: List[HistoryMessage], system_prompt: str) -> str:
        pass
