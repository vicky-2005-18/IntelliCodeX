package format

import "strings"

func JoinClean(tags []string, sep string) string {
    var cleaned []string
    for _, t := range tags {
        s := strings.TrimSpace(t)
        if s != "" {
            cleaned = append(cleaned, s)
        }
    }
    // Remove trailing separator
    return strings.Join(cleaned, sep)
}