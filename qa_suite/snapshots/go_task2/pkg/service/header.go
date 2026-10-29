package service

import "tagsvc/pkg/format"

func BuildTagHeader(tags []string) string {
    return format.JoinClean(tags, ", ")
}
