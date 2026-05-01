import fitz  # PyMuPDF


def chunk_pdf(pdf_bytes: bytes, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = ""
    for page in doc:
        full_text += page.get_text() + " "
    doc.close()
    return _split(full_text, chunk_size, overlap)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    return _split(text, chunk_size, overlap)


def _split(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
        i += chunk_size - overlap
    return chunks
