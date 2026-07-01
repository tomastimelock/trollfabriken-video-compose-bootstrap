# Implemented in task #33
from video_compose.renderers.base import BaseRenderer
class StillRenderer(BaseRenderer):
    def render(self, segment, data, width, height, fps): raise NotImplementedError
