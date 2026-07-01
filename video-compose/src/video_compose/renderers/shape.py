# Implemented in task #32
from video_compose.renderers.base import BaseRenderer
class ShapeRenderer(BaseRenderer):
    def render(self, segment, data, width, height, fps): raise NotImplementedError
