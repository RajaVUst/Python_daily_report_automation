"""Email the report via SMTP. All settings come from config.yaml (email:) and env (SMTP_USER/SMTP_PASSWORD)."""
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def _as_list(v) -> list[str]:
    if not v:
        return []
    return [x.strip() for x in (v.split(",") if isinstance(v, str) else v) if x and x.strip()]


def send(cfg: dict, subject: str, body: str, attachments: list[Path] | None = None) -> str:
    """Send an email. Returns a short status string; raises on SMTP errors."""
    if not cfg.get("enabled", False):
        return "disabled"
    to, cc, bcc = _as_list(cfg.get("to")), _as_list(cfg.get("cc")), _as_list(cfg.get("bcc"))
    if not to:
        raise ValueError("email.to is empty")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("from") or os.getenv("SMTP_USER", "")
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(body)
    for p in attachments or []:
        ctype, _ = mimetypes.guess_type(p.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)

    host, port = cfg["smtp_host"], int(cfg.get("smtp_port", 587))
    security = (cfg.get("security") or "starttls").lower()
    user, pw = os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD")
    ctx = ssl.create_default_context()
    timeout = int(cfg.get("timeout_seconds", 30))

    smtp_cls = smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP
    kwargs = {"context": ctx} if security == "ssl" else {}
    with smtp_cls(host, port, timeout=timeout, **kwargs) as s:
        if security == "starttls":
            s.starttls(context=ctx)
        if user and pw:
            s.login(user, pw)
        s.send_message(msg, to_addrs=to + cc + bcc)
    return f"sent to {', '.join(to + cc)}"
