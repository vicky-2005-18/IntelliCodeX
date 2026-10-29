package task1;

import java.util.List;

public class TextTransformer {
    public static String truncate(String text, int maxLength, String suffix) {
        if (text == null) return "";
        if (suffix == null) suffix = "";
        if (text.length() <= maxLength) return text;
        // Fix: Correct off-by-one error by using maxLength instead of maxLength + 1
        return text.substring(0, maxLength) + suffix;
    }

    public static String joinTokens(List<String> tokens, String delimiter) {
        if (tokens == null) return ""; // Fix: Return empty string when tokens is null
        if (delimiter == null) delimiter = "";
        return String.join(delimiter, tokens);
    }
}