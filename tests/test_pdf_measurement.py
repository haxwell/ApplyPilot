from __future__ import annotations

from pathlib import Path

from applypilot.scoring import pdf
from applypilot.scoring.pdf_render_model import ResumeRenderModel


def test_measure_html_page_count_uses_rendered_pdf_tokens(monkeypatch) -> None:
    def _fake_render_pdf(_html: str, output_path: str) -> None:
        Path(output_path).write_bytes(
            b"%PDF-1.7\n"
            b"1 0 obj << /Type /Page >> endobj\n"
            b"2 0 obj << /Type /Page >> endobj\n"
            b"3 0 obj << /Type /Page >> endobj\n"
        )

    monkeypatch.setattr(pdf, "render_pdf", _fake_render_pdf)

    assert pdf.measure_html_page_count("<html><body>Test</body></html>") == 3


def test_measure_model_page_count_uses_template_html(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def _fake_build_html_for_resume(
        model: ResumeRenderModel,
        template_name: str = pdf.DEFAULT_PDF_TEMPLATE,
    ) -> str:
        calls["model"] = model
        calls["template_name"] = template_name
        return "<html><body>Rendered</body></html>"

    def _fake_measure_html_page_count(html: str) -> int:
        calls["html"] = html
        return 2

    model = ResumeRenderModel(name="Alex Example")
    monkeypatch.setattr(pdf, "build_html_for_resume", _fake_build_html_for_resume)
    monkeypatch.setattr(pdf, "measure_html_page_count", _fake_measure_html_page_count)

    page_count = pdf.measure_model_page_count(model, template_name="compact")

    assert page_count == 2
    assert calls["model"] == model
    assert calls["template_name"] == "compact"
    assert calls["html"] == "<html><body>Rendered</body></html>"
