from automation.reports.localization import format_value


def test_localized_number_and_date_formats_are_deterministic():
    assert format_value(1234.5, language="en") == "1,234.50"
    assert format_value(1234.5, language="pt") == "1.234,50"
