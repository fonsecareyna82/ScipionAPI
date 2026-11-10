"""Signing in with an institution's account (OpenID Connect: Keycloak and the like).

sign_in_providers: the institutions an administrator set up, none by default. Each has the label of its button,
its issuer (the address its configuration is published under), the client id and the encrypted client secret the
institution gave, and what happens to a new person: an active account at once, or one waiting for activation.

user_identities: who a person is at a provider (its subject) and which account of ScipionWeb that is; an account
may have one per provider.

sign_in_requests: a sign-in under way (from the button to the provider's answer), with what proves the answer
belongs to it (state, nonce, code verifier); and the one-time codes the web exchanges for its session afterwards.
Both live a few minutes.

Revision ID: a8d2f6c4e159
Revises: f5b1d8e3a926
"""
from alembic import op


revision = "a8d2f6c4e159"
down_revision = "f5b1d8e3a926"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE sign_in_providers (
            id SERIAL PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            issuer TEXT NOT NULL,
            "clientId" TEXT NOT NULL,
            "clientSecret" TEXT,
            scopes TEXT NOT NULL DEFAULT 'openid email profile',
            "newAccounts" TEXT NOT NULL DEFAULT 'active' CHECK ("newAccounts" IN ('active', 'pending')),
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE user_identities (
            id SERIAL PRIMARY KEY,
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            "providerId" INTEGER NOT NULL REFERENCES sign_in_providers(id) ON DELETE CASCADE,
            subject TEXT NOT NULL,
            email TEXT,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "lastSignInAt" TIMESTAMPTZ,
            UNIQUE ("providerId", subject),
            UNIQUE ("providerId", "userId")
        )
    """)
    op.execute("""
        CREATE TABLE sign_in_requests (
            state TEXT PRIMARY KEY,
            "providerId" INTEGER REFERENCES sign_in_providers(id) ON DELETE CASCADE,
            nonce TEXT,
            "codeVerifier" TEXT,
            "returnTo" TEXT,
            "redirectUri" TEXT,
            "userId" INTEGER REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL DEFAULT 'request' CHECK (kind IN ('request', 'code')),
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade():
    op.execute("DROP TABLE sign_in_requests")
    op.execute("DROP TABLE user_identities")
    op.execute("DROP TABLE sign_in_providers")
