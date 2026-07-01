# Implemented in task #39
class Assembler:
    def __init__(self, spec, output_dir=None, progress_cb=None):
        self.spec = spec
    def run(self): raise NotImplementedError
    def render_segment_preview(self, segment_id, output_path=None): raise NotImplementedError
