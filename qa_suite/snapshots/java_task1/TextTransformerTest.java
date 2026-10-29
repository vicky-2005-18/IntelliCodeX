package task1;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

public class TextTransformerTest {
    @Test
    void testTruncateWithinLength() {
        assertEquals("hello", TextTransformer.truncate("hello", 10, "..."));
    }

    @Test
    void testTruncateExceedingLength() {
        // Exactly 5 chars + suffix
        assertEquals("Hello...", TextTransformer.truncate("Hello World", 5, "..."));
    }

    @Test
    void testJoinTokensNullSafe() {
        assertEquals("", TextTransformer.joinTokens(null, ","));
    }
}
