VALID_TRANSITIONS = {
    "new": ["needs_info", "confirmed", "cancelled"],
    "needs_info": ["confirmed", "cancelled"],
    "confirmed": ["in_progress", "cancelled"],
    "in_progress": ["shipped", "cancelled"],
    "shipped": ["delivered", "returned"],
    "delivered": [],
    "cancelled": [],
    "returned": [],
}


def can_transition(current: str, new: str) -> bool:
    if current == new:
        return True
    return new in VALID_TRANSITIONS.get(current, [])


def assert_valid_transition(current: str, new: str) -> None:
    if not can_transition(current, new):
        raise ValueError(f"Invalid order status transition: {current} -> {new}")

