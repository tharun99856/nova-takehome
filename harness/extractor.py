"""Document extraction using existing grader utilities.

Reads emails and attachments, extracts text using grader/extract.py,
handles scanned PDFs with OCR/vision fallback.
"""
import sys
from pathlib import Path
from email.utils import parsedate_to_datetime

# Pre-import pymupdf to ensure it's available for grader/extract.py
try:
    import pymupdf
    sys.modules['pymupdf'] = pymupdf  # Ensure it's in sys.modules
except ImportError as e:
    print(f"Warning: pymupdf not available: {e}", file=sys.stderr)

# Add grader to path for extract utility
sys.path.insert(0, str(Path(__file__).parent.parent / "grader"))
from extract import parse_eml, attachments, pages_of, pdf_is_image_only


class DocumentExtractor:
    """Extract text from mailbox documents."""
    
    def __init__(self, batch_dir: Path):
        self.batch_dir = Path(batch_dir)
        self.batch_name = batch_dir.name
    
    def extract_batch(self) -> list[dict]:
        """Extract all documents from batch directory."""
        documents = []
        
        for eml_file in sorted(self.batch_dir.glob("*.eml")):
            if eml_file.name.startswith("_"):
                continue
            
            try:
                doc_info = self._extract_email(eml_file)
                documents.append(doc_info)
            except Exception as e:
                print(f"Error extracting {eml_file.name}: {e}", file=sys.stderr)
                # Don't silently discard - add with error marker
                documents.append({
                    "batch": self.batch_name,
                    "file": eml_file.name,
                    "received_date": None,
                    "content": eml_file.read_bytes(),
                    "doc_type": "eml",
                    "is_scan": False,
                    "pages": [],
                    "attachments": [],
                    "error": str(e)
                })
        
        return documents
    
    def _extract_email(self, eml_file: Path) -> dict:
        """Extract email and its attachments."""
        content = eml_file.read_bytes()
        msg = parse_eml(content)
        
        # Get received date from email Date header
        date_header = msg["Date"]
        if date_header:
            dt = parsedate_to_datetime(str(date_header))
            received_date = dt.strftime("%Y-%m-%d")
        else:
            received_date = None
        
        # Extract email body pages
        email_pages = pages_of(content, "eml")
        
        doc_info = {
            "batch": self.batch_name,
            "file": eml_file.name,
            "received_date": received_date,
            "content": content,
            "doc_type": "eml",
            "is_scan": False,
            "pages": email_pages,
            "attachments": []
        }
        
        # Extract attachments
        for att_name, att_data in attachments(content):
            if not att_name:
                continue
            
            ext = att_name.rsplit(".", 1)[-1].lower() if "." in att_name else ""
            
            try:
                is_scan = False
                if ext == "pdf":
                    is_scan = pdf_is_image_only(att_data)
                
                # Extract text pages (will be empty for scanned PDFs)
                att_pages = pages_of(att_data, ext) if ext in ("pdf", "xlsx") else []
                
                doc_info["attachments"].append({
                    "name": att_name,
                    "content": att_data,
                    "ext": ext,
                    "is_scan": is_scan,
                    "pages": att_pages,
                    "doc_ref": f"{eml_file.name}#{att_name}"
                })
            except Exception as e:
                print(f"Error extracting attachment {att_name}: {e}", file=sys.stderr)
                # Store with error marker
                doc_info["attachments"].append({
                    "name": att_name,
                    "content": att_data,
                    "ext": ext,
                    "is_scan": False,
                    "pages": [],
                    "doc_ref": f"{eml_file.name}#{att_name}",
                    "error": str(e)
                })
        
        return doc_info


def ocr_scan(pdf_data: bytes) -> list[str]:
    """OCR a scanned PDF using rapidocr fallback.
    
    Returns pages as text. Spaces may be missing inside words.
    Caller should normalize when comparing.
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        
        # Convert PDF to images and OCR each page
        import pymupdf
        doc = pymupdf.open(stream=pdf_data, filetype="pdf")
        
        pages = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap()
            img_data = pix.tobytes("png")
            
            # OCR the image
            result, _ = engine(img_data)
            if result:
                # Sort boxes by vertical position, then horizontal
                boxes = sorted(result, key=lambda x: (x[0][0][1], x[0][0][0]))
                page_text = "\n".join(box[1] for box in boxes)
                pages.append(page_text)
            else:
                pages.append("")
        
        doc.close()
        return pages
    except Exception as e:
        print(f"OCR failed: {e}", file=sys.stderr)
        return []
