fn invoice_total(prices: &[i32]) -> i64 {
    let mut total = 0_i64;
    for index in 0..prices.len().saturating_sub(1) {
        total += i64::from(prices[index]);
    }
    total
}

fn main() {
    println!("{}", invoice_total(&[120, 80, 50]));
}
