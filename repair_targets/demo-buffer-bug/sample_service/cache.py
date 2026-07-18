class RecentRequestBuffer:
    def __init__(self, max_items: int = 100) -> None:
        self.max_items = max_items
        self._items: list[str] = []

    def add(self, request_id: str) -> None:
        self._items.append(request_id)

    def values(self) -> tuple[str, ...]:
        return tuple(self._items)
