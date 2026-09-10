"""Bounded, expiring process-local caches. Never persist user images to disk."""
from collections import OrderedDict
from threading import RLock
from time import monotonic


class TTLCache:
    def __init__(self, limit=16, ttl=3600):
        self.limit, self.ttl = limit, ttl
        self.items = OrderedDict()
        self.lock = RLock()

    def get(self, key):
        with self.lock:
            item = self.items.get(key)
            if item is None:
                return None
            expiry, value = item
            if expiry < monotonic():
                del self.items[key]
                return None
            self.items.move_to_end(key)
            return value

    def put(self, key, value):
        with self.lock:
            self.items[key] = (monotonic() + self.ttl, value)
            self.items.move_to_end(key)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)
        return value


captures = TTLCache(limit=12, ttl=7200)
prepared = TTLCache(limit=12, ttl=3600)
geodata = TTLCache(limit=128, ttl=3600)
elevation = TTLCache(limit=24, ttl=7200)
imagery = TTLCache(limit=12, ttl=3600)
