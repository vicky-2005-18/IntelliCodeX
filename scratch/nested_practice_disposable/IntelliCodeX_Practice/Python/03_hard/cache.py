class LRUCache:
    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError('capacity must be positive')
        self.capacity = capacity
        self.values = {}
        self.order = []

    def get(self, key):
        return self.values.get(key, -1)

    def put(self, key, value):
        if key in self.values:
            self.order.remove(key)
        elif len(self.values) == self.capacity:
            oldest = self.order.pop(0)
            del self.values[oldest]
        self.values[key] = value
        self.order.append(key)

if __name__ == '__main__':
    cache = LRUCache(2)
    cache.put(1, 100)
    cache.put(2, 200)
    print(cache.get(1))
    cache.put(3, 300)
    print(cache.get(2))
    print(cache.get(1))
