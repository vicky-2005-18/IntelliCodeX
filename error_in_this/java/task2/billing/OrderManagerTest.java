package billing;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class OrderManagerTest {
    @Test
    void testDefaultOverload() {
        DiscountCalculator calc = new DiscountCalculator();
        assertEquals(100.0, calc.calculateNet(100.0), 0.001);
    }

    @Test
    void testCustomDiscountOverload() {
        OrderManager mgr = new OrderManager();
        // 200 with 15% discount -> 170.0
        assertEquals(170.0, mgr.finalizeOrder(200.0, 0.15), 0.001);
    }
}
