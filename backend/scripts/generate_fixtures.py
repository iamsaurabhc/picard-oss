from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def generate_sample_nda(path: Path, pages: int = 5) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for i in range(pages):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 750, "NON-DISCLOSURE AGREEMENT")
        c.setFont("Helvetica", 11)
        c.drawString(72, 720, f"Section {i + 1}. Confidentiality")
        c.drawString(72, 700, "The parties agree to keep confidential all proprietary information.")
        c.drawString(72, 680, "Party ABC shall not disclose materials after 18/05/2019.")
        c.drawString(72, 660, "Condition C applies to all subsidiary obligations.")
        c.showPage()
    c.save()


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "test" / "fixtures"
    root.mkdir(parents=True, exist_ok=True)
    generate_sample_nda(root / "sample-nda-20p.pdf", pages=20)
    generate_sample_nda(root / "multi-entity.pdf", pages=3)
    print(f"Wrote fixtures to {root}")
