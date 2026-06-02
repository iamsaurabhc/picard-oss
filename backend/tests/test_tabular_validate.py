from app.schemas import TabularColumn
from app.services.tabular_validate import (
    enforce_format_summary,
    format_instruction,
    is_litigation_na_column,
    litigation_na_summary,
    needs_metadata_retry,
    needs_shorter_retry,
)
from app.tabular.presets import prompt_for_column


def test_format_instruction_date():
    assert "DD Mon YYYY" in format_instruction("date")


def test_enforce_format_summary_truncates_text():
    long_text = " ".join(["word"] * 80)
    out = enforce_format_summary(long_text, "text")
    assert len(out.split()) <= 60


def test_enforce_format_summary_date_extracts():
    out = enforce_format_summary(
        "The order was signed on 15 March 2024 by the Commission.",
        "date",
    )
    assert "15 March 2024" in out or "2024" in out


def test_litigation_na_column():
    assert is_litigation_na_column("litigation", "governing_law")
    assert not is_litigation_na_column("regulatory", "governing_law")
    assert "litigation" in litigation_na_summary("governing_law")


def test_needs_metadata_retry_when_not_specified():
    assert needs_metadata_retry(
        "Not specified",
        "governing_law",
        {"governing_law": "Competition Act 2002, India"},
    )


def test_needs_shorter_retry():
    col = TabularColumn(key="x", label="X", format="date", prompt="p")
    assert needs_shorter_retry(" ".join(["word"] * 30), col)


def test_regulatory_prompt_variant():
    col = TabularColumn(
        key="governing_law",
        label="Governing Law",
        format="text",
        prompt='State only "New York Law".',
    )
    reg = prompt_for_column(col, "regulatory")
    assert "statute" in reg.casefold() or "regulatory" in reg.casefold()
    assert prompt_for_column(col, None) == col.prompt
