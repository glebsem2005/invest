from abc import ABC, abstractmethod


class ModelStrategy(ABC):
    @abstractmethod
    def send_message(self, prompt: str) -> str: ...


class ChatGPTStrategy(ModelStrategy): ...


class GigaChatStrategy(ModelStrategy): ...


class PerplexityStrategy(ModelStrategy): ...


class DeepseekStrategy(ModelStrategy): ...


class ModelAPI:
    def __init__(self, strategy: ModelStrategy) -> None:
        self._strategy = strategy

    @property
    def strategy(self) -> ModelStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: ModelStrategy) -> None:
        self._strategy = strategy

    def send_message(self, prompt: str) -> str:
        return self._strategy.send_message(prompt)
