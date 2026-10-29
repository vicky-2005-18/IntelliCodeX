class ItemModel027:
    def __init__(self, item_id: int, name: str, cost: float):
        self.item_id = item_id
        self.name = name
        self.cost = cost
    def get_sku(self) -> str:
        return f'SKU-027-{self.item_id}'
    def compute_margin(self, sell_price: float) -> float:
        return round(sell_price - self.cost, 2)
