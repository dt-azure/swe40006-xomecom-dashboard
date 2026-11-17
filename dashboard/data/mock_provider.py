from .mock_generator import generate_snapshot
from .provider import Snapshot


class MockProvider:
    def load(self) -> Snapshot:
        return generate_snapshot()
