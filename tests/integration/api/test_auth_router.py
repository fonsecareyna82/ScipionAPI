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
def test_SignupCreatesUser(authClient, fakeMapper):
    response = authClient.post(
        "/auth/signup",
        json={
            "email": "new@example.com",
            "password": "secret123",
            "firstName": "Yunior",
            "lastName": "Fonseca",
            "institution": "CNB-CSIC",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["message"] == "User created. Please check your inbox to verify your email."
    assert body["userId"] == 1

    createdUser = fakeMapper.usersByEmail["new@example.com"]
    assert createdUser["hashedPassword"] == "hashed::secret123"
    assert createdUser["role"] == "user"
    assert createdUser["isActive"] is True
    assert createdUser["isVerified"] is True


def test_SignupRejectsDuplicatedEmail(authClient, fakeMapper):
    fakeMapper.usersByEmail["existing@example.com"] = {
        "id": 9,
        "email": "existing@example.com",
    }

    response = authClient.post(
        "/auth/signup",
        json={
            "email": "existing@example.com",
            "password": "secret123",
            "firstName": "John",
            "lastName": "Doe",
            "institution": "Lab",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_VerifyEmailMarksUserAsVerified(authClient, fakeMapper):
    userId = fakeMapper.insertUser(
        email="verify@example.com",
        hashedPassword="hashed::secret123",
        firstName="Test",
        lastName="User",
        institution="Lab",
        role="user",
        isActive=True,
        isVerified=False,
        verificationCode="code-123",
    )

    response = authClient.post("/auth/verify", params={"verificationCode": "code-123"})

    assert response.status_code == 200
    assert response.json() == {"message": "Email verified successfully"}
    assert userId in fakeMapper.verifiedUserIds
    assert fakeMapper.usersById[userId]["isVerified"] is True


def test_VerifyEmailRejectsInvalidCode(authClient):
    response = authClient.post("/auth/verify", params={"verificationCode": "invalid-code"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid verification code"


def test_ResendCodeFailsWhenUserDoesNotExist(authClient):
    response = authClient.post(
        "/auth/resend-code",
        json={"email": "missing@example.com"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_ResendCodeFailsWhenUserAlreadyVerified(authClient, fakeMapper):
    fakeMapper.insertUser(
        email="verified@example.com",
        hashedPassword="hashed::secret123",
        firstName="Verified",
        lastName="User",
        institution="Lab",
        role="user",
        isActive=True,
        isVerified=True,
        verificationCode="old-code",
    )

    response = authClient.post(
        "/auth/resend-code",
        json={"email": "verified@example.com"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "User is already verified"


def test_ResendCodeUpdatesCodeAndSendsEmail(authClient, fakeMapper):
    userId = fakeMapper.insertUser(
        email="pending@example.com",
        hashedPassword="hashed::secret123",
        firstName="Pending",
        lastName="User",
        institution="Lab",
        role="user",
        isActive=True,
        isVerified=False,
        verificationCode="old-code",
    )

    response = authClient.post(
        "/auth/resend-code",
        json={"email": "pending@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Verification code resent"}

    assert len(fakeMapper.updatedVerificationCodes) == 1
    updatedUserId, newCode = fakeMapper.updatedVerificationCodes[0]
    assert updatedUserId == userId
    assert newCode != "old-code"


def test_LoginFailsWhenUserDoesNotExist(authClient):
    response = authClient.post(
        "/auth/login",
        json={"email": "missing@example.com", "password": "secret123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_LoginFailsWhenPasswordIsWrong(authClient, fakeMapper):
    fakeMapper.insertUser(
        email="user@example.com",
        hashedPassword="hashed::different",
        firstName="Test",
        lastName="User",
        institution="Lab",
        role="user",
        isActive=True,
        isVerified=True,
        verificationCode="code-1",
    )

    response = authClient.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secret123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_LoginFailsWhenEmailIsNotVerified(authClient, fakeMapper):
    fakeMapper.insertUser(
        email="user@example.com",
        hashedPassword="hashed::secret123",
        firstName="Test",
        lastName="User",
        institution="Lab",
        role="user",
        isActive=True,
        isVerified=False,
        verificationCode="code-1",
    )

    response = authClient.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secret123"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Email not verified"


def test_LoginReturnsAccessAndRefreshTokens(authClient, fakeMapper):
    fakeMapper.insertUser(
        email="user@example.com",
        hashedPassword="hashed::secret123",
        firstName="Test",
        lastName="User",
        institution="Lab",
        role="user",
        isActive=True,
        isVerified=True,
        verificationCode="code-1",
    )

    response = authClient.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secret123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accessToken"] == "access::user@example.com"
    assert body["refreshToken"] == "refresh::user@example.com"
    assert body["tokenType"] == "bearer"


def test_GetMeReturnsCurrentUserProfile(authClient, fakeMapper):
    fakeMapper.usersById[1] = {
        "id": 1,
        "email": "user@example.com",
        "firstName": "Yunior",
        "lastName": "Fonseca",
        "institution": "CNB-CSIC",
        "role": "user",
        "isActive": True,
        "isVerified": True,
    }

    response = authClient.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["email"] == "user@example.com"


def test_GetMeReturns404WhenProfileIsMissing(authClient):
    response = authClient.get("/auth/me")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_UpdateMePersistsOnlyProvidedFields(authClient, fakeMapper):
    fakeMapper.usersById[1] = {
        "id": 1,
        "email": "user@example.com",
        "firstName": "Old",
        "lastName": "Name",
        "institution": "Old Institution",
        "role": "user",
        "isActive": True,
        "isVerified": True,
    }

    response = authClient.put(
        "/auth/me",
        json={"firstName": "New", "institution": "CNB-CSIC"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["firstName"] == "New"
    assert body["institution"] == "CNB-CSIC"
    assert body["lastName"] == "Name"

    assert fakeMapper.updatedUserFields == [
        (1, {"firstName": "New", "institution": "CNB-CSIC"})
    ]


def test_UpdateMeReturns404WhenUserDisappearsAfterUpdate(authClient, fakeMapper):
    fakeMapper.usersById[1] = {
        "id": 1,
        "email": "user@example.com",
        "firstName": "Old",
        "lastName": "Name",
        "institution": "Lab",
        "role": "user",
        "isActive": True,
        "isVerified": True,
    }

    def deleteOnUpdate(userId, fields):
        fakeMapper.updatedUserFields.append((userId, fields))
        fakeMapper.usersById.pop(userId, None)

    fakeMapper.updateUserFields = deleteOnUpdate

    response = authClient.put(
        "/auth/me",
        json={"firstName": "New"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_RefreshFailsWhenTokenIsMissing(authClient):
    response = authClient.post("/auth/refresh", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing token"


def test_RefreshFailsWhenTokenIsInvalid(authClient):
    response = authClient.post("/auth/refresh", json={"token": "invalid-refresh"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid refresh token"


def test_RefreshReturnsNewAccessToken(authClient):
    response = authClient.post("/auth/refresh", json={"token": "valid-refresh"})

    assert response.status_code == 200
    assert response.json() == {"accessToken": "access::user@example.com"}