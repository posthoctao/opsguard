from sample_service import RecentRequestBuffer


def test_buffer_keeps_only_the_most_recent_items() -> None:
    buffer = RecentRequestBuffer(max_items=3)

    for request_id in ["r1", "r2", "r3", "r4", "r5"]:
        buffer.add(request_id)

    assert buffer.values() == ("r3", "r4", "r5")


def test_buffer_rejects_non_positive_capacity() -> None:
    try:
        RecentRequestBuffer(max_items=0)
    except ValueError as exc:
        assert "正整数" in str(exc)
    else:
        raise AssertionError("容量不是正整数时应抛出 ValueError")
