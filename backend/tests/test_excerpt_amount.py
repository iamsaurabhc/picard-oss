from app.services.excerpt_selector import _best_excerpt, has_amount_signal


def test_amount_anchored_excerpt():
    text = (
        "Argument on demurrers to the declaration was adjourned until after the trial. "
        "The plaintiff claimed damages in the sum of £1,000 and was otherwise greatly damnified."
    )
    excerpt = _best_excerpt(text, 200, prefer_amounts=True)
    assert has_amount_signal(excerpt)
    assert "1,000" in excerpt or "£" in excerpt
