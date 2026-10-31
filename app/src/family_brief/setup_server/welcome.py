"""Welcome: the page's language, the AI picked and whether it's ready, the partner or only me,
and pilot feedback."""
from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from .. import failure, feedback, setup_save
from ..system import desktop, profile, secrets
from . import ai
from .context import (LANGUAGES, Action, Phase, Reply, ais, chats, claude_missing, not_offered,
                      section)

# What checking the AI picked says. The gateway needs nothing on the Mac, so it's always ready,
# and it has no chat to carry on in.
AI_RESULTS = ("ready", "not-installed", "signed-out", "check-failed")


class RecipientAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    language: Literal["fi", "en", "zh"]


class WelcomeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ai: Literal["claude", "codex", "gateway"]
    # Everyone who gets the Brief, as many as the Household has: the address the Brief is sent
    # from isn't one of them, unless it's typed in here too.
    recipients: list[RecipientAnswer] = Field(min_length=1)
    feedback: StrictBool


class Welcome(Phase):
    def routes(self) -> dict[str, Action]:
        return {"api/language": self.choose_language, "api/ai": self.check_ai,
                "api/welcome": self.save_welcome}

    def state(self, progress: dict[str, Any]) -> dict[str, Any]:
        return {"languages": [{"code": c, "name": n} for c, n in LANGUAGES.items()],
                "language": self.context.chosen_language(),
                "preselected": preferred_language(),
                # Which system's words the page uses, the AIs it offers here, and those it
                # installs itself, so Welcome needn't wait for them.
                "system": profile.current().system,
                "ais": list(ais()),
                "installs": sorted(profile.current().page_installs),
                # What Copy puts with a failure's reason, for the family to send us.
                "about": failure.about(),
                # In tmux or SSH, macOS may not let this server save the passwords in the Keychain.
                "keychain": {"reachable": secrets.reachable()},
                "welcome": self._welcome(progress)}

    def choose_language(self, raw: Any) -> Reply:
        """Saves the language picked as the setup parent's: the Household's summary_language,
        which the Recipients without a language of their own read."""
        if not (isinstance(raw, dict) and set(raw) == {"language"} and raw["language"] in LANGUAGES):
            return HTTPStatus.BAD_REQUEST, setup_save.outcome(
                "invalid-answers", "Pick one of the page's languages.",
                errors=[f"language: should be one of {', '.join(LANGUAGES)}"])
        with self.context.connect.lock:
            out = setup_save.save(self.context.config, {"language": raw["language"]})
        if out["result"] != "saved":
            return HTTPStatus.CONFLICT, out
        return HTTPStatus.OK, {**out, "language": raw["language"]}

    def check_ai(self, raw: Any) -> Reply:
        """Checks that the AI picked is installed and signed in, with its own status check."""
        if not (isinstance(raw, dict) and set(raw) == {"ai"} and raw["ai"] in ais()):
            return HTTPStatus.BAD_REQUEST, not_offered()
        name = raw["ai"]
        if name == "gateway":
            return HTTPStatus.OK, {"result": "ready", "ai": name}
        program = ai.program(self.context, name)
        if program is None:
            missing = claude_missing() if name == "claude" else {"result": "not-installed"}
            return HTTPStatus.OK, {**missing, "ai": name}
        return HTTPStatus.OK, {**ai.status(self.context, program, name), "ai": name}

    def save_welcome(self, raw: Any) -> Reply:
        """Saves Welcome's choices: the AI, everyone who gets the Brief, and pilot feedback, and
        moves setup on to Connect. The Recipients are saved here, as typed: the address the Brief
        is sent from is not added to them."""
        try:
            answer = WelcomeAnswer.model_validate(raw)
        except ValidationError as e:
            return HTTPStatus.BAD_REQUEST, setup_save.invalid(e)
        if answer.ai not in ais():
            return HTTPStatus.BAD_REQUEST, not_offered()
        household = self.context.chosen_language() or "en"
        recipients = [
            {"address": r.address.strip().lower(),
             **({"language": r.language} if r.language != household else {})}
            for r in answer.recipients
        ]
        answers: dict[str, Any] = {
            "ai": answer.ai,
            "recipients": recipients,
            "progress": {"phase": "connect", "source": "wilma"},
        }
        if answer.feedback or feedback.pilot_form():  # without a pilot Form, setup save refuses yes
            answers["feedback"] = {"enabled": answer.feedback}
        with self.context.connect.lock:
            out = setup_save.save(self.context.config, answers)
        if out["result"] != "saved":
            return (HTTPStatus.BAD_REQUEST if out["result"] == "invalid-answers"
                    else HTTPStatus.CONFLICT), out
        if answer.ai in chats():  # the gateway has no chat to install, nor Windows yet
            self.context.chat.install(answer.ai)
        return HTTPStatus.OK, out

    def _welcome(self, progress: dict[str, Any]) -> dict[str, Any]:
        """Welcome's choices as saved, each with its default until it is."""
        data = self.context.data()
        language = self.context.chosen_language() or preferred_language()
        backend = section(data, "llm").get("backend")
        offered = ais()
        enabled = section(data, "feedback").get("enabled")
        # None when this version ships no pilot Form: the page doesn't ask, so nothing half-set
        # is ever written.
        pilot = (enabled if isinstance(enabled, bool) else True) if feedback.pilot_form() else None
        return {"ai": backend if backend in offered else offered[0],
                "recipients": _recipients(data, language), "feedback": pilot}


def _recipients(data: dict[str, Any], language: str) -> list[dict[str, str]]:
    """Everyone who gets the Brief as the config has them, or one empty row to fill in. The
    address the Brief is sent from is not one of them: only what was typed is."""
    to = section(data, "email").get("to")
    rows = []
    for r in (to if isinstance(to, list) else []):
        r = {"address": r} if isinstance(r, str) else r
        if isinstance(r, dict) and r.get("address"):
            rows.append({"address": str(r["address"]), "language": r.get("language") or language})
    return rows or [{"address": "", "language": language}]


def preferred_language() -> str:
    """The first of the page's languages among the computer's preferred ones, else English."""
    for tag in desktop.preferred_languages():
        language = re.split(r"[-_]", tag)[0].lower()
        if language in LANGUAGES:
            return language
    return "en"
