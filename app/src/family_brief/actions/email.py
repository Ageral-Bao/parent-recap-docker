"""The email Action: one call for the Brief, its first one from setup and Weekend Picks, sent
through the maintainers' gateway from Parent Recap's own address (ADR 0028, ADR 0032). The
Household's Gmail is only ever read.

Local patch: with `email.sender: gmail` the same calls go out through the Household's own Gmail
with its App Password (SMTP over SSL), so the Brief comes from an address the family reads."""
from __future__ import annotations

import base64
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import TYPE_CHECKING

from .. import gateway as api
from .. import send_key

if TYPE_CHECKING:
    from ..config import Config

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # implicit TLS


Attachments = list[tuple[str, bytes, str]]


def send(cfg: Config, subject: str, body_text: str, to_addrs: list[str],
         body_html: str | None = None, attachments: Attachments | None = None) -> None:
    """Send one email to `to_addrs` through the gateway `cfg` names. A send that fails raises,
    saying why.

    attachments: (filename, payload, mime type) tuples, e.g. ("events.ics", b"...", "text/calendar").
    """
    if not to_addrs:
        log.warning("email: no recipients configured")
        return
    if cfg.email.sender == "gmail":
        gmail(cfg, subject, body_text, to_addrs, body_html, attachments)
        return
    try:
        gateway(cfg.llm.gateway_url, subject, body_text, to_addrs, body_html, attachments)
    except api.NoKey as e:
        # A Household that sent through its own Gmail before ADR 0032 has no key: one whose AI is
        # its own Claude Code or Codex gets a send-only one on request (ADR 0033), and the
        # Brief goes out once a Recipient confirms.
        if not e.missing or not send_key.may_request(cfg):
            raise
        status = send_key.ensure(cfg)
        raise api.GatewayError(f"no Gateway Key was stored: {send_key.describe(status)}") from None


def write_to(cfg: Config) -> str | None:
    """Where a Recipient writes instead of replying: nowhere with the Gmail sender, since the Brief
    comes from the Household's own address and a reply reaches it like any other email, so there is
    no note to add; through the gateway it is the setup parent, the first Recipient, since the
    Brief comes from the gateway's address, which nobody reads."""
    if cfg.email.sender == "gmail":
        return None
    return cfg.email.to[0].address if cfg.email.to else None


def gmail(cfg: Config, subject: str, body_text: str, to_addrs: list[str],
          body_html: str | None = None, attachments: Attachments | None = None) -> None:
    """Send through the Household's own Gmail, SMTP over SSL, with the App Password stored for its
    username. Gmail's App Passwords work for SMTP as well as IMAP, so the one the Gmail collector
    already needs is all this takes. A send that fails raises, saying why."""
    from ..collectors.gmail import get_app_password, username_of

    sender = username_of(cfg)
    if not sender:
        raise RuntimeError("email.sender is gmail, but the config names no gmail.username")
    password = get_app_password(sender)
    if not password:
        raise RuntimeError(f"no Gmail App Password is stored for {sender}: the Brief can't be "
                           "sent from it")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Parent Recap <{sender}>"
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    for filename, payload, mime in attachments or []:
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(payload, maintype=maintype or "application",
                           subtype=subtype or "octet-stream", filename=filename)

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(),
                              timeout=60) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise RuntimeError(f"Gmail refused the Brief from {sender}: {e}") from None
    log.info("email sent through Gmail as %s: subject=%r (%d Recipients, %d chars, %d attachments)",
             sender, subject, len(to_addrs), len(body_text), len(attachments or []))


def gateway(url: str, subject: str, body_text: str, to_addrs: list[str],
            body_html: str | None = None, attachments: Attachments | None = None) -> None:
    """Send through the gateway's Brief relay at `url` with the Gateway Key (ADR 0028). A refused
    send raises GatewayError as a failed model call does, and is never tried again here: the
    relay may have sent it, and the next run sends the night again. Without a Gateway Key it
    raises NoKey."""
    gateway_key = api.key()
    body: dict = {"to": list(to_addrs), "subject": subject, "text": body_text}
    if body_html:
        body["html"] = body_html
    if attachments:
        body["attachments"] = [{"filename": f, "content_type": mime,
                                "data": base64.b64encode(payload).decode("ascii")}
                               for f, payload, mime in attachments]
    try:
        refused, unconfirmed = api.read_sent(api.post_brief(url, gateway_key, body))
    except api.GatewayError as e:
        raise api.GatewayError(api.without_key(str(e), gateway_key), e.status) from None
    if refused:
        log.warning("email: the mail service refused %d of %d Recipients", refused, len(to_addrs))
    if unconfirmed:
        log.warning("email: not sent to %s, who %s not confirmed their address yet: %s",
                    ", ".join(unconfirmed), "has" if len(unconfirmed) == 1 else "have",
                    api.CONFIRM_HOW)
    log.info("email sent through the gateway at %s: subject=%r (%d Recipients, %d chars, "
             "%d attachments)", api.host(url), subject, len(to_addrs), len(body_text),
             len(attachments or []))
