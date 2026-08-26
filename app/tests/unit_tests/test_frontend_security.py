from pathlib import Path


def test_frontend_sanitizes_markdown_before_x_html() -> None:
    html = (Path(__file__).parents[3] / "frontend" / "index.html").read_text()
    assert "DOMPurify.sanitize" in html
    assert "dompurify@3.4.13" in html
    assert "dompurify@3.4.0" not in html
    assert "dompurify@3.2.6" not in html
    assert "ALLOWED_URI_REGEXP: /^https?:\\/\\//i" in html
    assert "marked.parse" in html
