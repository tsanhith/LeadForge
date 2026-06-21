from app.ingest.column_map import map_headers


def test_apollo_style_headers():
    headers = ["First Name", "Title", "Company Name", "Website", "Email", "Industry"]
    mapping = map_headers(headers)
    assert mapping["Title"] == "position"
    assert mapping["Company Name"] == "company"
    assert mapping["Website"] == "website"
    assert mapping["Email"] == "email"
    assert mapping["Industry"] == "industry"


def test_zoominfo_style_aliases():
    headers = ["Full Name", "Job Title", "Account", "Company URL", "Work Email", "Mobile"]
    mapping = map_headers(headers)
    assert mapping["Job Title"] == "position"
    assert mapping["Account"] == "company"
    assert mapping["Company URL"] == "website"
    assert mapping["Work Email"] == "email"
    assert mapping["Mobile"] == "phone"


def test_each_field_claimed_once():
    headers = ["Email", "Email Address"]  # both map to email
    mapping = map_headers(headers)
    assert list(mapping.values()).count("email") == 1
