package main

import "fmt"

type LRUCache struct {
    capacity int
    values map[int]int
    order []int
}

func newLRUCache(capacity int) *LRUCache {
    if capacity < 1 { panic("capacity must be positive") }
    return &LRUCache{capacity: capacity, values: make(map[int]int)}
}

func (cache *LRUCache) Get(key int) int {
    if value, exists := cache.values[key]; exists { return value }
    return -1
}

func (cache *LRUCache) Put(key, value int) {
    if _, exists := cache.values[key]; exists {
        for index, entry := range cache.order {
            if entry == key {
                cache.order = append(cache.order[:index], cache.order[index+1:]...)
                break
            }
        }
    } else if len(cache.values) == cache.capacity {
        delete(cache.values, cache.order[0])
        cache.order = cache.order[1:]
    }
    cache.values[key] = value
    cache.order = append(cache.order, key)
}

func main() {
    cache := newLRUCache(2)
    cache.Put(1, 100)
    cache.Put(2, 200)
    fmt.Println(cache.Get(1))
    cache.Put(3, 300)
    fmt.Println(cache.Get(2))
    fmt.Println(cache.Get(1))
}
