"""
PDF Report Generator.
Generates PDF from Markdown using weasyprint.
Synchronous for small reports; shaped for future async dispatch.
"""
import markdown
from backend.utils.logger import get_logger

logger = get_logger(__name__)


def markdown_to_pdf_bytes(md_content: str) -> bytes:
    """
    Convert Markdown to PDF bytes using weasyprint.
    Returns empty bytes on failure (degrades gracefully).
    """
    try:
        from weasyprint import HTML, CSS
        html_content = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <style>
          body {{ font-family: sans-serif; margin: 40px; line-height: 1.6; }}
          h1 {{ color: #1a1a2e; border-bottom: 2px solid #e44d26; padding-bottom: 8px; }}
          h2 {{ color: #16213e; margin-top: 24px; }}
          h3 {{ color: #0f3460; }}
          code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
          th {{ background-color: #f2f2f2; }}
          .risk-high {{ color: #c0392b; font-weight: bold; }}
          .risk-medium {{ color: #e67e22; }}
          .risk-low {{ color: #27ae60; }}
        </style>
        </head>
        <body>
        {html_content}
        </body>
        </html>
        """
        pdf_bytes = HTML(string=styled_html).write_pdf()
        logger.info("PDF generated", extra={"size_bytes": len(pdf_bytes)})
        return pdf_bytes
    except Exception as exc:
        logger.error("PDF generation failed", extra={"error": str(exc)}, exc_info=exc)
        return b""


async def generate_pdf_report(audit_id: str) -> bytes:
    """
    Build markdown report and convert to PDF.
    Runs weasyprint synchronously in executor to avoid blocking event loop.
    """
    import asyncio
    from backend.tools.report_builder import build_markdown_report
    md = await build_markdown_report(audit_id)
    loop = asyncio.get_event_loop()
    pdf_bytes = await loop.run_in_executor(None, markdown_to_pdf_bytes, md)
    return pdf_bytes
