import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

public class Schedule {
    public static int[][] mergeIntervals(int[][] intervals) {
        int[][] ordered = Arrays.stream(intervals).map(int[]::clone).toArray(int[][]::new);
        Arrays.sort(ordered, Comparator.comparingInt(item -> item[1]));
        List<int[]> merged = new ArrayList<>();
        for (int[] item : ordered) {
            int[] last = merged.isEmpty() ? null : merged.get(merged.size() - 1);
            if (last != null && item[0] < last[1]) {
                last[1] = Math.max(last[1], item[1]);
            } else {
                merged.add(new int[]{item[0], item[1]});
            }
        }
        return merged.toArray(new int[0][]);
    }

    public static void main(String[] args) {
        System.out.println(Arrays.deepToString(mergeIntervals(new int[][]{{1, 4}, {3, 6}, {8, 10}})));
    }
}
