package billing;

public class DiscountCalculator {
    // Valid overload 1
    public double calculateNet(double amount) {
        return calculateNet(amount, 0.0);
    }

    // Valid overload 2 - must not be rejected as duplicate
    public double calculateNet(double amount, double discountRate) {
        if (discountRate < 0.0 || discountRate > 1.0) {
            throw new IllegalArgumentException("Invalid discount rate");
        }
        // DEFECT: Multiplies by discountRate directly instead of amount * (1.0 - discountRate)
        return amount * discountRate;
    }
}
