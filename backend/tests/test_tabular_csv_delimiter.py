from app.tabular import read_table_file


def test_semicolon_csv_with_unquoted_thousands_commas_uses_semicolon(tmp_path):
    path = tmp_path / "finance.csv"
    path.write_bytes(
        (
            "\ufeffEntry No;Posting Date;GL Account;Account Name;Cost Centre;Vendor;Amount;Currency;Approved By;Approver Email\n"
            "JE-202600001;15/09/2026;5300;Cloud Hosting;CC-IT;Amazon Web Services;162,118.32;INR;"
            "Ananya Das;ananya.das@example.com\n"
        ).encode("utf-8")
    )

    (sheet,) = read_table_file(path)

    assert sheet.columns == [
        "Entry No",
        "Posting Date",
        "GL Account",
        "Account Name",
        "Cost Centre",
        "Vendor",
        "Amount",
        "Currency",
        "Approved By",
        "Approver Email",
    ]
    assert len(sheet.rows) == 1
    assert sheet.rows[0]["Entry No"] == "JE-202600001"
    assert sheet.rows[0]["Amount"] == "162,118.32"
    assert sheet.rows[0]["Vendor"] == "Amazon Web Services"
    assert sheet.profile["Amount"].type == "float"
