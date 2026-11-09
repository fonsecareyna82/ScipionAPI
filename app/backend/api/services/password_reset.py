"""Resetting a forgotten password with a one-time link mailed to the account's address.

Asking always answers the same, whether the address has an account or not (nobody learns who has one). An
active account gets a link, through the notifications (kind account.passwordReset: mailed at once, never shown in
the web, its text forgotten once sent), that lasts LINK_MINUTES and is used once; asking again within
ASK_EVERY_MINUTES sends nothing new. Only the token's hash is kept.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any, Dict

from fastapi import HTTPException, status

from app.backend.mapper.password_reset_mapper import PasswordResetPostgresqlMapper

logger = logging.getLogger(__name__)

LINK_MINUTES = 60
ASK_EVERY_MINUTES = 5
ANSWER = "If the address has an active account, a mail with a link to choose a new password is on its way."


def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode()).hexdigest()


def askReset(mapper, email: str) -> Dict[str, Any]:
    """Mail a reset link to the account of the address, if any; answers the same either way."""
    from app.backend.api.services.mail_service import MailService
    from app.backend.api.services.notifications import Notifications

    user = mapper.getUserByEmail(str(email or "").strip())
    if not user or not user.get("isActive") or user.get("deletingAt"):
        return {"message": ANSWER}
    resets = PasswordResetPostgresqlMapper(mapper.db)
    if resets.recentlyAsked(user["id"], ASK_EVERY_MINUTES):
        return {"message": ANSWER}
    publicUrl = MailService(mapper.db).publicUrl()
    if not publicUrl:
        logger.warning("A password reset was asked, but the web's address is not set (Settings, Notifications): "
                       "the link cannot be mailed")
        return {"message": ANSWER}
    token = secrets.token_urlsafe(32)
    resets.create(user["id"], _hash(token), LINK_MINUTES)
    body = ("Someone (you, we hope) asked to choose a new password for your ScipionWeb account %s.\n\n"
            "Choose it here, within %d minutes (the link works once):\n%s/reset-password?token=%s\n\n"
            "If it was not you, ignore this mail: your password stays as it is."
            % (user["email"], LINK_MINUTES, publicUrl, token))
    Notifications(mapper.db).notify([int(user["id"])], "account.passwordReset", "ScipionWeb: choose a new password",
                                    body)
    return {"message": ANSWER}


def reset(mapper, token: str, password: str) -> Dict[str, Any]:
    """Set the new password of the link's account; 400 when the link is not valid (used, expired, unknown)."""
    from app.backend.utils.security import hashPassword

    resets = PasswordResetPostgresqlMapper(mapper.db)
    found = resets.valid(_hash(token)) if token else None
    if not found:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="This link no longer works: it was used, it expired, or it is not right. "
                                   "Ask for a new one.")
    mapper.updateUserPassword(int(found["userId"]), hashPassword(password))
    resets.use(found["userId"])
    return {"message": "Your new password is set: sign in with it.", "userId": int(found["userId"])}
