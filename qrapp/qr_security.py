"""Signed QR payload helpers for student attendance codes."""

from django.conf import settings
from django.core import signing


QR_SALT = "qrapp.student-qr-v1"


def _signer():
    return signing.Signer(salt=QR_SALT)


def make_qr_token(student_id: str) -> str:
    return _signer().sign(str(student_id).strip())


def verify_qr_token(token, expected_student_id=None):
    """
    Verify a signed token and return the student_id embedded in it.
    Raises signing.BadSignature on failure.
    """
    student_id = _signer().unsign(str(token).strip())
    if expected_student_id and str(expected_student_id).strip() != str(student_id).strip():
        raise signing.BadSignature("Token student ID mismatch")
    return student_id


def qr_require_signature() -> bool:
    return getattr(settings, "QR_REQUIRE_SIGNATURE", False)


def parse_scan_payload(decoded_text: str = "", student_id: str = "", qr_token: str = ""):
    """
    Parse scanner payload into student_id + optional token.
    Accepts either structured QR text or plain student_id / token fields.
    """
    text = (decoded_text or "").strip()
    sid = (student_id or "").strip()
    token = (qr_token or "").strip()

    if text:
        lines = [line.strip() for line in text.replace("\r", "").split("\n") if line.strip()]
        for line in lines:
            if line.upper().startswith("ID:"):
                sid = line.split(":", 1)[1].strip() or sid
            elif line.upper().startswith("TOKEN:"):
                token = line.split(":", 1)[1].strip() or token

        # Plain handheld scanners may send only the student id
        if not sid and len(lines) == 1 and ":" not in lines[0]:
            sid = lines[0].strip()

    return sid, token


def resolve_scanned_student_id(decoded_text="", student_id="", qr_token=""):
    """
    Return (student_id, error_message).
    - Signed token preferred
    - Legacy unsigned QR allowed unless QR_REQUIRE_SIGNATURE=True
    """
    sid, token = parse_scan_payload(decoded_text, student_id, qr_token)

    if token:
        try:
            verified_id = verify_qr_token(token, expected_student_id=sid or None)
            return verified_id, None
        except signing.BadSignature:
            return None, "Invalid or tampered QR code."

    if not sid:
        return None, "No student ID provided."

    if qr_require_signature():
        return None, "Unsigned QR codes are not accepted. Please regenerate QR codes."

    return sid, None
