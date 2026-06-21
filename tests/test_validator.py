from app.ingest.validator import normalize_website, validate_rows


def test_normalize_website_adds_scheme():
    assert normalize_website("abc-logistics.com") == "https://abc-logistics.com"
    assert normalize_website("http://X.com/path/") == "http://x.com/path"
    assert normalize_website("") is None


def test_flags_missing_and_invalid():
    rows = [
        {"company": "ABC", "website": "abc.com", "email": "a@abc.com"},
        {"company": "NoSite", "email": "bad-email"},      # missing website, invalid email
        {"name": "Ghost"},                                 # no identity -> invalid
    ]
    result = validate_rows(rows)
    assert result[0].valid and result[0].flags == []
    assert "missing_website" in result[1].flags
    assert "invalid_email" in result[1].flags
    assert result[1].valid  # still has company identity
    assert not result[2].valid
    assert "no_identity" in result[2].flags


def test_duplicate_detection_by_email():
    rows = [
        {"company": "A", "email": "dup@a.com"},
        {"company": "A", "email": "dup@a.com"},
    ]
    result = validate_rows(rows)
    assert result[0].valid
    assert not result[1].valid
    assert "duplicate" in result[1].flags
