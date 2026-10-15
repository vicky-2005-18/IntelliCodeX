class LRUCache {
    constructor(capacity) {
        if (!Number.isInteger(capacity) || capacity < 1) {
            throw new Error('capacity must be a positive integer');
        }
        this.capacity = capacity;
        this.values = new Map();
    }

    get(key) {
        return this.values.has(key) ? this.values.get(key) : -1;
    }

    put(key, value) {
        if (this.values.has(key)) {
            this.values.delete(key);
        } else if (this.values.size === this.capacity) {
            this.values.delete(this.values.keys().next().value);
        }
        this.values.set(key, value);
    }
}

const cache = new LRUCache(2);
cache.put(1, 100);
cache.put(2, 200);
console.log(cache.get(1));
cache.put(3, 300);
console.log(cache.get(2));
console.log(cache.get(1));
