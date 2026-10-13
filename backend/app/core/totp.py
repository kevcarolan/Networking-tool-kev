"""Two-factor sign-in: time-based one-time codes (RFC 6238, the 6-digit codes of Microsoft
Authenticator, Google Authenticator, Authy, 1Password and the like), and recovery codes
for a lost phone.

A code is accepted for its 30-second step and the steps either side (clocks drift), and
never twice: the last step used is kept, so a code seen over someone's shoulder can't be
used again. Recovery codes are random, kept only as hashes, and work once each.
"""

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1  # steps either side accepted
RECOVERY_CODES = 10


def new_secret() -> str:
    """A random 160-bit secret, as the base32 text authenticator apps take."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def step_now(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def verify(secret: str, code: str, last_step: int = -1, now: float | None = None) -> int | None:
    """The step the code belongs to, or None (wrong, too old, or already used)."""
    code = "".join(c for c in (code or "") if c.isdigit())
    if len(code) != DIGITS or not secret:
        return None
    current = step_now(now)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(secret: str, account: str, issuer: str) -> str:
    """The otpauth:// link the QR code holds."""
    label = quote(f"{issuer}:{account}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def qr_svg(text: str) -> str:
    """The link as a QR code (SVG), drawn on the server: no outside service sees it."""
    import segno

    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=5, border=2, xmldecl=False,
                                     svgns=True, dark="#000", light="#fff")
    return out.getvalue().decode()


def recovery_codes() -> list[str]:
    """Ten one-time codes like 'k7m2-q9xd-4tph' (no 0/o, 1/l to misread)."""
    alphabet = "23456789abcdefghjkmnpqrstuvwxyz"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
            for _ in range(RECOVERY_CODES)]


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().replace(" ", "").encode()).hexdigest()


def use_recovery(hashes: list[str], code: str) -> list[str] | None:
    """The remaining hashes once this code is used, or None if it isn't one of them."""
    h = hash_code(code)
    for i, stored in enumerate(hashes):
        if hmac.compare_digest(stored, h):
            return hashes[:i] + hashes[i + 1:]
    return None
