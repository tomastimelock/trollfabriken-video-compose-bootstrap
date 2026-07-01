# Implemented in task #31
from abc import ABC, abstractmethod
import numpy as np
class BaseRenderer(ABC):
    @abstractmethod
    def render(self, segment, data, width, height, fps) -> list: ...
