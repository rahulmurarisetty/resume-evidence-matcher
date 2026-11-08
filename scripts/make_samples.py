"""Regenerate the sample PDF and DOCX resumes in samples/generated/.

Every sample is fictional. Real resumes never go in this repository.

    python scripts/make_samples.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.builders import PdfStyle, build_docx, build_pdf  # noqa: E402


def main() -> None:
    source_dir = ROOT / "samples" / "resumes"
    out_dir = ROOT / "samples" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_dir.glob("*.md")):
        markup = source.read_text(encoding="utf-8")
        pdf = out_dir / f"{source.stem}.pdf"
        docx = out_dir / f"{source.stem}.docx"
        pdf.write_bytes(build_pdf(markup, PdfStyle(bullet_mode="separate")))
        docx.write_bytes(build_docx(markup, skills_as_table=True))
        print(f"wrote {pdf.relative_to(ROOT)} and {docx.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
