# Implemented in task #30
from video_compose.data.fetcher import DataFetcher
class SQLFetcher(DataFetcher):
    def fetch(self, config): raise NotImplementedError
