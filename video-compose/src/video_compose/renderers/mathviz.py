# Implemented in task #31
from video_compose.renderers.base import BaseRenderer
class MathvizRenderer(BaseRenderer):
    def render(self, segment, data, width, height, fps): raise NotImplementedError
