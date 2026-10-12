import re

from app.rag import _strip_repeated_lines


def test_pdf_repeated_line_filter_preserves_ticket_ids_and_record_fields():
    pages = [
        "\n".join(
            [
                "ITSM Incident Knowledge Base",
                f"Incident ID: INC20260000{number}",
                "Status: Resolved",
                f"Page {number} of 3",
            ]
        )
        for number in range(1, 4)
    ]

    cleaned = _strip_repeated_lines(pages)
    text = "\n".join(cleaned)

    assert "ITSM Incident Knowledge Base" not in text
    assert len(re.findall(r"INC20260000\d+", text)) == 3
    assert text.count("Status: Resolved") == 3
    assert not re.search(r"(?m)^Page \d+ of 3$", text)
