package task1;

import java.util.List;

public class TextTransformer {
    public static String truncate(String text, int maxLength, String suffix) {
        if (text == null) return "";
        if (suffix == null) suffix = "";
        if (text.length() <= maxLength) return text;
        // DEFECT 1: Off-by-one error (maxLength + 1 includes an extra character)
        return text.substring(0, maxLength + 1) + suffix;
    }

    public static String joinTokens(List<String> tokens, String delimiter) {
        // DEFECT 2: Throws NullPointerException when tokens is null instead of returning empty string
        if (tokens.isEmpty()) return "";
        return String.join(delimiter == null ? "" : delimiter, tokens);
    }
}
