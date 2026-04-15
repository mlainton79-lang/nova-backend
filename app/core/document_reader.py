import base64

def extract_text_from_document(document_text=None, document_base64=None, document_mime=None, document_name=None) -> str:
    if document_text:
        return document_text[:50000]
    if document_base64 and document_mime:
        if "pdf" in document_mime.lower():
            return f"[PDF document: {document_name or 'Unknown'}. Binary content provided as base64.]"
        if "image" in document_mime.lower():
            return ""
    return ""
