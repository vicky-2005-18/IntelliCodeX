#include <stdio.h>
#include <stdlib.h>

typedef struct { int start; int end; } Interval;

static int compare_intervals(const void *left, const void *right) {
    const Interval *a = left;
    const Interval *b = right;
    return (a->end > b->end) - (a->end < b->end);
}

int merge_intervals(const Interval input[], int count, Interval output[]) {
    if (count <= 0) return 0;
    Interval *ordered = malloc((size_t)count * sizeof(*ordered));
    if (!ordered) return -1;
    for (int i = 0; i < count; i++) ordered[i] = input[i];
    qsort(ordered, (size_t)count, sizeof(*ordered), compare_intervals);
    int used = 0;
    for (int i = 0; i < count; i++) {
        if (used > 0 && ordered[i].start < output[used - 1].end) {
            if (ordered[i].end > output[used - 1].end) output[used - 1].end = ordered[i].end;
        } else {
            output[used++] = ordered[i];
        }
    }
    free(ordered);
    return used;
}

int main(void) {
    const Interval input[] = {{1, 4}, {3, 6}, {8, 10}};
    Interval output[3];
    int count = merge_intervals(input, 3, output);
    if (count < 0) return 1;
    for (int i = 0; i < count; i++) printf("[%d, %d]\n", output[i].start, output[i].end);
    return 0;
}
