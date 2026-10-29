package billing;

public class OrderManager {
    private final DiscountCalculator calculator = new DiscountCalculator();

    public double finalizeOrder(double amount, double discountRate) {
        return calculator.calculateNet(amount, discountRate);
    }
}
