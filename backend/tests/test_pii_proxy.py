from app.services.pii_proxy import PIIProxy, StreamingPIIRestorer


def test_token_determinism():
    proxy = PIIProxy()
    proxy.register_text("Contact rahul@acme.in")
    token = proxy.reverse_map["rahul@acme.in"]
    proxy.register_text("Email rahul@acme.in again")
    assert proxy.reverse_map["rahul@acme.in"] == token


def test_indian_regex_patterns():
    proxy = PIIProxy()
    text = "PAN ABCDE1234F email x@y.co phone +91-9876543210 aadhaar 1234 5678 9012"
    proxy.register_text(text)
    anon = proxy.anonymize(text)
    assert "ABCDE1234F" not in anon
    assert "x@y.co" not in anon
    assert "9876543210" not in anon
    assert "1234 5678 9012" not in anon


def test_restore_roundtrip():
    proxy = PIIProxy()
    raw = "Draft for rahul@acme.in"
    proxy.register_text(raw)
    anon = proxy.anonymize(raw)
    assert "rahul@acme.in" not in anon
    token = proxy.reverse_map["rahul@acme.in"]
    restored = proxy.restore(anon + f" thanks {token}")
    assert "rahul@acme.in" in restored


def test_streaming_split_token_restore():
    forward = {"<PERSON_1>": "Rahul Mehta"}
    restorer = StreamingPIIRestorer(forward)
    out = restorer.feed("<PER")
    assert out == ""
    out += restorer.feed("SON_1> signed")
    assert out == "Rahul Mehta signed"
    assert restorer.flush() == ""
