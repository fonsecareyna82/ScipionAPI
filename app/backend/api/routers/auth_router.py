# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
# routers/auth_router.py

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status, Body
from app.backend.api.schemas.user_schema import (UserCreate, UserOut, LoginResponse, LoginRequest, ResendCodeRequest,
                                                 UserUpdate, ChangePasswordRequest, ForgotPasswordRequest,
                                                 ResetPasswordRequest)
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.utils.security import hashPassword, verifyPassword
from app.backend.utils.jwt import createAccessToken, createRefreshToken, verifyToken
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services.access_service import AccessService
from app.backend.api.audit import recordAudit

router = APIRouter(prefix="/auth", tags=["Authentication"])

# A new account waits for an administrator; a disabled one stays out
ACCOUNT_NOT_ACTIVE_MESSAGE = "This account is not active. An administrator has to activate it."


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    userData: UserCreate,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    # Check if email is already registered
    existingUser = mapper.getUserByEmail(userData.email)
    if existingUser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Hash the password and generate a verification code
    hashedPassword = hashPassword(userData.password)
    verificationCode = str(uuid.uuid4())

    # Insert user into the database via the mapper. The account cannot sign in until an
    # administrator activates it (and gives it its permissions)
    userId = mapper.insertUser(
        email=userData.email,
        hashedPassword=hashedPassword,
        firstName=userData.firstName,
        lastName=userData.lastName,
        institution=userData.institution,
        role="user",
        isActive=False,
        isVerified=True,
        verificationCode=verificationCode,
    )

    # The default roles (User, unless an administrator chose others); the account still waits for activation
    AccessService(mapper.db).giveDefaultRoles(userId)
    recordAudit(mapper, {"id": userId, "email": userData.email}, "auth.signUp", "user", userId,
                userData.email)

    # Return confirmation message and new user ID
    return {
        "message": "User created. An administrator has to activate the account before it can sign in.",
        "userId": userId,
        "pendingActivation": True,
    }


@router.post("/verify", status_code=status.HTTP_200_OK)
def verifyEmail(
    verificationCode: str,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    user = mapper.getUserByVerificationCode(verificationCode)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )
    mapper.verifyUser(user["id"])
    return {"message": "Email verified successfully"}


@router.post("/resend-code", status_code=status.HTTP_200_OK)
async def resendVerificationCode(
    request: ResendCodeRequest,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    user = mapper.getUserByEmail(request.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if user["isVerified"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already verified"
        )
    newCode = str(uuid.uuid4())
    mapper.updateUserVerificationCode(user["id"], newCode)
    return {"message": "Verification code updated"}


@router.post("/login", response_model=LoginResponse)
def login(
    loginData: LoginRequest,
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    user = mapper.getUserByEmail(loginData.email)
    if not user:
        recordAudit(mapper, None, "auth.signInFailed", details={"reason": "unknown account"},
                    actorEmail=loginData.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid credentials")

    if not verifyPassword(loginData.password, user["hashedPassword"]):
        recordAudit(mapper, user, "auth.signInFailed", details={"reason": "wrong password"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid credentials")

    if not bool(user.get("isActive", True)):
        recordAudit(mapper, user, "auth.signInFailed", details={"reason": "account not active"})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ACCOUNT_NOT_ACTIVE_MESSAGE,
        )

    if not user["isVerified"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Email not verified")

    accessToken = createAccessToken(data={"sub": user["email"]})
    refreshToken = createRefreshToken(data={"sub": user["email"]})
    recordAudit(mapper, user, "auth.signIn")
    return LoginResponse(accessToken=accessToken, refreshToken=refreshToken, tokenType="bearer")


@router.get(
    "/me",
    response_model=UserOut,
    status_code=status.HTTP_200_OK
)
def getMe(
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Return the authenticated user's profile.
    """
    # Fetch up-to-date user fields from the database
    userProfile = mapper.getUserById(currentUser["id"])
    if not userProfile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return dict(userProfile, permissions=currentUser.get("permissions") or [],
                isSystemAdmin=bool(currentUser.get("isSystemAdmin")))


@router.put(
    "/me",
    response_model=UserOut,
    status_code=status.HTTP_200_OK
)
def updateMe(
    updates: UserUpdate,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Update the authenticated user's profile fields.
    Only fields present in the request (exclude_unset) will be updated.
    """
    # Extract only provided fields from the payload
    updateFields = updates.dict(exclude_unset=True)

    # Persist updates via the mapper
    mapper.updateUserFields(currentUser["id"], updateFields)

    # Fetch the latest profile data
    userProfile = mapper.getUserById(currentUser["id"])
    if not userProfile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return userProfile


@router.put("/me/password", status_code=status.HTTP_200_OK)
def changeMyPassword(
    passwordData: ChangePasswordRequest,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    user = mapper.getUserById(currentUser["id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not verifyPassword(passwordData.currentPassword, user["hashedPassword"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if passwordData.currentPassword == passwordData.newPassword:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    mapper.updateUserPassword(
        currentUser["id"],
        hashPassword(passwordData.newPassword),
    )
    recordAudit(mapper, currentUser, "auth.passwordChanged", "user", currentUser["id"], currentUser.get("email"))

    return {"message": "Password changed successfully"}


@router.post("/refresh")
def refreshToken(
    payload: dict = Body(...),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    refresh_token = payload.get("token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Missing token")

    decoded = verifyToken(refresh_token, expected_type="refresh")
    user_email = decoded.get("sub")
    if not user_email:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = mapper.getUserByEmail(user_email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if not bool(user.get("isActive", True)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    new_access_token = createAccessToken(data={"sub": user_email})
    return {"accessToken": new_access_token}


@router.get("/password-reset", status_code=status.HTTP_200_OK)
def passwordResetAvailable(mapper: PostgresqlFlatMapper = Depends(getMapper)):
    """Whether a forgotten password can be reset by mail (the sign-in page offers it only then)."""
    from app.backend.api.services.mail_service import MailService

    mail = MailService(mapper.db)
    return {"available": mail.sending() and bool(mail.publicUrl())}


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgotPassword(payload: ForgotPasswordRequest, mapper: PostgresqlFlatMapper = Depends(getMapper)):
    """Mail a one-time link to choose a new password; answers the same whether the address has an account."""
    from app.backend.api.services import password_reset

    return password_reset.askReset(mapper, payload.email)


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def resetPassword(payload: ResetPasswordRequest, mapper: PostgresqlFlatMapper = Depends(getMapper)):
    """Set a new password with the link's token."""
    from app.backend.api.services import password_reset

    result = password_reset.reset(mapper, payload.token, payload.password)
    user = mapper.getUserById(result["userId"]) or {}
    recordAudit(mapper, {"id": result["userId"], "email": user.get("email")}, "auth.passwordReset", "user",
                result["userId"], user.get("email"))
    return {"message": result["message"]}



# Signing in with an institution's account (OpenID Connect) -------------------------------------------------------

def _ownOrigins(request, mapper) -> list:
    """The origins this installation's web is served from: the API's own, and the public address if set."""
    origins = ["%s://%s" % (request.url.scheme, request.headers.get("host") or request.url.netloc)]
    try:
        from app.backend.api.services.mail_service import MailService

        public = MailService(mapper.db).publicUrl()
        if public:
            origins.append(public)
    except Exception:
        pass
    return origins


def _signInPage(message: str):
    from fastapi.responses import HTMLResponse
    from html import escape

    return HTMLResponse("<!doctype html><meta charset='utf-8'><title>Sign in</title>"
                        "<p style='font:16px sans-serif;margin:2em'>%s</p>" % escape(message), status_code=400)


@router.get("/providers")
def listSignInProviders(mapper: PostgresqlFlatMapper = Depends(getMapper)):
    """The institutions one may sign in with (the buttons of the sign-in page); none until an administrator adds
    one."""
    from app.backend.mapper.sign_in_mapper import SignInPostgresqlMapper

    return [{"key": provider["key"], "label": provider["label"]}
            for provider in SignInPostgresqlMapper(mapper.db).providers(enabledOnly=True)]


@router.get("/oidc/{key}/start", name="oidcStart")
def startSignIn(key: str, request: Request, returnTo: str, mapper: PostgresqlFlatMapper = Depends(getMapper)):
    """Send the browser to the institution's sign-in page; it comes back to oidcCallback."""
    from fastapi.responses import RedirectResponse
    from app.backend.api.services import sign_in

    if not sign_in.returnAllowed(returnTo, _ownOrigins(request, mapper)):
        return _signInPage("This sign-in was not asked from this installation's web.")
    try:
        target = sign_in.start(mapper.db, key, str(request.url_for("oidcCallback", key=key)), returnTo)
    except sign_in.SignInError as error:
        return RedirectResponse(sign_in.withQuery(returnTo, {"error": str(error)}), status_code=302)
    return RedirectResponse(target, status_code=302)


@router.get("/oidc/{key}/callback", name="oidcCallback")
def finishSignIn(key: str, request: Request, mapper: PostgresqlFlatMapper = Depends(getMapper)):
    """The institution's answer: back to the web with a one-time code (or why it did not work)."""
    from fastapi.responses import RedirectResponse
    from app.backend.api.services import sign_in

    params = request.query_params
    pending = sign_in.takeRequest(mapper.db, params.get("state", ""))
    if not pending:
        return _signInPage("This sign-in expired or was already used. Go back to ScipionWeb and sign in again.")
    returnTo = pending["returnTo"]
    if params.get("error"):
        reason = params.get("error_description") or params.get("error")
        return RedirectResponse(sign_in.withQuery(returnTo, {"error": "The institution did not sign you in: %s"
                                                                      % reason}), status_code=302)
    try:
        code = sign_in.finish(mapper.db, mapper, pending, params.get("code", ""))
    except sign_in.SignInError as error:
        return RedirectResponse(sign_in.withQuery(returnTo, {"error": str(error)}), status_code=302)
    return RedirectResponse(sign_in.withQuery(returnTo, {"code": code}), status_code=302)


@router.post("/oidc/exchange", response_model=LoginResponse)
def exchangeSignInCode(payload: dict = Body(...), mapper: PostgresqlFlatMapper = Depends(getMapper)):
    """The web's session for the one-time code it was sent back with."""
    from app.backend.api.services import sign_in

    try:
        user = sign_in.exchange(mapper.db, mapper, str(payload.get("code") or ""))
    except sign_in.SignInError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error))
    recordAudit(mapper, user, "auth.signIn", details={"method": "institution"})
    return LoginResponse(accessToken=createAccessToken(data={"sub": user["email"]}),
                         refreshToken=createRefreshToken(data={"sub": user["email"]}), tokenType="bearer")
