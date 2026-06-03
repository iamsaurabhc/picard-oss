from app.services.excerpt_selector import focus_sentences_excerpt, split_sentences


def test_split_sentences_basic():
    text = "The plaintiff claimed damages. The sum was £1,000. Judgment followed."
    sents = split_sentences(text)
    assert len(sents) >= 2


def test_focus_picks_amount_sentence():
    text = (
        "Appeal from the County Court. Various procedural matters were discussed. "
        "The plaintiff claimed damages in the sum of £1,000 for negligence."
    )
    excerpt = focus_sentences_excerpt(
        text,
        200,
        question="What damages did the plaintiff claim?",
        prefer_amounts=True,
    )
    assert excerpt
    assert "£1,000" in excerpt or "1,000" in excerpt
