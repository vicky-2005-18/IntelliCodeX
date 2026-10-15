class LRUCache {
    private values = new Map<number, number>();

    constructor(private capacity: number) {
        if (!Number.isInteger(capacity) || capacity < 1) {
            throw new Error('capacity must be a positive integer');
        }
    }

    get(key: number): number {
        return this.values.get(key) ?? -1;
    }

    put(key: number, value: number): void {
        if (this.values.has(key)) {
            this.values.delete(key);
        } else if (this.values.size === this.capacity) {
            const oldest = this.values.keys().next().value;
            if (oldest !== undefined) this.values.delete(oldest);
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
