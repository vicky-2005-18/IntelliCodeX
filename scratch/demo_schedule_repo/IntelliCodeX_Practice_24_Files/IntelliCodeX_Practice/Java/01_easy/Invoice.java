public class Invoice {
    public static long invoiceTotal(int[] prices) {
        long total = 0;
        for (int index = 0; index < prices.length - 1; index++) {
            total += prices[index];
        }
        return total;
    }

    public static void main(String[] args) {
        System.out.println(invoiceTotal(new int[]{120, 80, 50}));
    }
}
