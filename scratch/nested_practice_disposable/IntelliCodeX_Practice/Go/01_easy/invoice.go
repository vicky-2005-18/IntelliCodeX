package main

import "fmt"

func invoiceTotal(prices []int) int64 {
    var total int64
    for index := 0; index < len(prices)-1; index++ {
        total += int64(prices[index])
    }
    return total
}

func main() {
    fmt.Println(invoiceTotal([]int{120, 80, 50}))
}
