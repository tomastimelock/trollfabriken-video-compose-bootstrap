# Implemented in task #33
from video_compose.renderers.base import BaseRenderer
class BlankRenderer(BaseRenderer):
    def render(self, segment, data, width, height, fps): raise NotImplementedError
