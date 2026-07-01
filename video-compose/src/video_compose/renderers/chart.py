# Implemented in task #32
from video_compose.renderers.base import BaseRenderer
class ChartRenderer(BaseRenderer):
    def render(self, segment, data, width, height, fps): raise NotImplementedError
