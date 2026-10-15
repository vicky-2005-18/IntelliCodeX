#include <stdio.h>

typedef struct {
    int capacity;
    int size;
    int keys[64];
    int values[64];
} LRUCache;

int cache_init(LRUCache *cache, int capacity) {
    if (capacity < 1 || capacity > 64) return 0;
    cache->capacity = capacity;
    cache->size = 0;
    return 1;
}

int cache_get(LRUCache *cache, int key) {
    for (int i = 0; i < cache->size; i++) {
        if (cache->keys[i] == key) return cache->values[i];
    }
    return -1;
}

void cache_put(LRUCache *cache, int key, int value) {
    int position = -1;
    for (int i = 0; i < cache->size; i++) {
        if (cache->keys[i] == key) { position = i; break; }
    }
    if (position < 0 && cache->size == cache->capacity) position = 0;
    if (position >= 0) {
        for (int i = position; i + 1 < cache->size; i++) {
            cache->keys[i] = cache->keys[i + 1];
            cache->values[i] = cache->values[i + 1];
        }
        cache->size--;
    }
    cache->keys[cache->size] = key;
    cache->values[cache->size++] = value;
}

int main(void) {
    LRUCache cache;
    if (!cache_init(&cache, 2)) return 1;
    cache_put(&cache, 1, 100);
    cache_put(&cache, 2, 200);
    printf("%d\n", cache_get(&cache, 1));
    cache_put(&cache, 3, 300);
    printf("%d\n", cache_get(&cache, 2));
    printf("%d\n", cache_get(&cache, 1));
    return 0;
}
