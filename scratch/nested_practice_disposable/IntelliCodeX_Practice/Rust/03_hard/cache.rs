use std::collections::{HashMap, VecDeque};

struct LruCache {
    capacity: usize,
    values: HashMap<i32, i32>,
    order: VecDeque<i32>,
}

impl LruCache {
    fn new(capacity: usize) -> Self {
        assert!(capacity > 0);
        Self { capacity, values: HashMap::new(), order: VecDeque::new() }
    }

    fn get(&mut self, key: i32) -> i32 {
        self.values.get(&key).copied().unwrap_or(-1)
    }

    fn put(&mut self, key: i32, value: i32) {
        if self.values.contains_key(&key) {
            self.order.retain(|entry| *entry != key);
        } else if self.values.len() == self.capacity {
            if let Some(oldest) = self.order.pop_front() {
                self.values.remove(&oldest);
            }
        }
        self.values.insert(key, value);
        self.order.push_back(key);
    }
}

fn main() {
    let mut cache = LruCache::new(2);
    cache.put(1, 100);
    cache.put(2, 200);
    println!("{}", cache.get(1));
    cache.put(3, 300);
    println!("{}", cache.get(2));
    println!("{}", cache.get(1));
}
