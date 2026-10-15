import java.util.LinkedHashMap;

public class Cache {
    static class LRUCache {
        private final int capacity;
        private final LinkedHashMap<Integer, Integer> values = new LinkedHashMap<>();

        LRUCache(int capacity) {
            if (capacity < 1) throw new IllegalArgumentException("capacity must be positive");
            this.capacity = capacity;
        }

        int get(int key) {
            return values.getOrDefault(key, -1);
        }

        void put(int key, int value) {
            if (values.containsKey(key)) {
                values.remove(key);
            } else if (values.size() == capacity) {
                values.remove(values.keySet().iterator().next());
            }
            values.put(key, value);
        }
    }

    public static void main(String[] args) {
        LRUCache cache = new LRUCache(2);
        cache.put(1, 100);
        cache.put(2, 200);
        System.out.println(cache.get(1));
        cache.put(3, 300);
        System.out.println(cache.get(2));
        System.out.println(cache.get(1));
    }
}
