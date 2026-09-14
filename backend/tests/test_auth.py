"""Authentication regressions; no database or network service required."""
import base64
from datetime import datetime
import hashlib
import importlib
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import Depends, FastAPI
import httpx
from jose import jwt

from app.config import settings
from app.core import auth
from app.core.tenant_resolver import TenantResolver
from app.database import supabase

login_module = importlib.import_module("app.api.v1.login")


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings_patch = patch.multiple(
            settings, supabase_url=None, supabase_service_role_key=None,
            supabase_anon_key=None,
        )
        self.settings_patch.start()
        auth.clear_auth_cache()
        app = FastAPI()
        app.include_router(login_module.router)

        @app.get("/protected")
        async def protected(user=Depends(auth.authenticate_request)):
            return {"tenant_id": user.tenant_id, "email": user.email}

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        auth.clear_auth_cache()
        self.settings_patch.stop()

    def token(self, **overrides):
        claims = {
            "id": "user-sunset", "email": "sunset@propertyflow.com",
            "aud": "authenticated", "exp": int(time.time()) + 300,
            "app_metadata": {"tenant_id": "tenant-a", "role": "user"},
        }
        claims.update(overrides)
        return jwt.encode(claims, settings.secret_key, algorithm="HS256")

    async def protected(self, token):
        return await self.client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"},
        )

    async def test_supplied_accounts_remain_isolated_across_cached_requests(self):
        tokens = []
        for email, password, tenant in (
            ("sunset@propertyflow.com", "client_a_2024", "tenant-a"),
            ("ocean@propertyflow.com", "client_b_2024", "tenant-b"),
        ):
            response = await self.client.post(
                "/auth/login", json={"email": email, "password": password},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["user"]["tenant_id"], tenant)
            tokens.append((response.json()["access_token"], tenant))
        for token, tenant in tokens + list(reversed(tokens)):
            response = await self.protected(token)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["tenant_id"], tenant)

    async def test_local_login_rejects_wrong_password_and_legacy_accounts(self):
        for email, password in (
            ("sunset@propertyflow.com", "wrong"),
            ("ocean@propertyflow.com", "client_a_2024"),
            ("candidate@propertyflow.com", "anything"),
            ("sid@theflexliving.com", "anything"),
            ("unknown@example.com", "anything"),
            ("sunset@propertyflow.com", " client_a_2024 "),
        ):
            with self.subTest(email=email, password=password):
                response = await self.client.post(
                    "/auth/login", json={"email": email, "password": password},
                )
                self.assertEqual(response.status_code, 401)

    async def test_missing_invalid_unsigned_and_expired_tokens_are_401(self):
        self.assertEqual((await self.client.get("/protected")).status_code, 401)
        encoded = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
        unsigned = encoded({"alg": "none"}) + "." + encoded({
            "email": "candidate@propertyflow.com", "exp": time.time() + 60,
        }) + "."
        for token in (
            "mock-token-123", "invalid", unsigned,
            self.token(exp=int(time.time()) - 60), self.token(aud="wrong"),
            self.token()[:-8] + "tampered",
        ):
            with self.subTest(token=token[:15]):
                self.assertEqual((await self.protected(token)).status_code, 401)

    async def test_signed_token_requires_expiration(self):
        token = jwt.encode({
            "id": "user-sunset", "email": "sunset@propertyflow.com",
            "aud": "authenticated", "app_metadata": {"tenant_id": "tenant-a"},
        }, settings.secret_key, algorithm="HS256")
        self.assertEqual((await self.protected(token)).status_code, 401)

    async def test_missing_trusted_tenant_is_403_even_for_known_email(self):
        for metadata in ({}, {"tenant_id": "tenant-b"}):
            token = self.token(app_metadata={}, user_metadata=metadata)
            self.assertEqual((await self.protected(token)).status_code, 403)
        self.assertIsNone(await TenantResolver.resolve_tenant_id(
            "unknown", "unknown@example.com",
        ))

    async def test_verified_tenant_claims_override_email_and_user_metadata(self):
        response = await self.protected(self.token(
            email="ocean@propertyflow.com", id="user-ocean",
            app_metadata={"tenant_id": "tenant-a"},
            user_metadata={"tenant_id": "tenant-b"},
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tenant_id"], "tenant-a")
        response = await self.protected(self.token(
            app_metadata={}, tenant_id="tenant-b",
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tenant_id"], "tenant-b")

    async def test_cached_authentication_cannot_outlive_token_expiration(self):
        expires = int(time.time()) + 60
        token = self.token(exp=expires)
        self.assertEqual((await self.protected(token)).status_code, 200)
        key = hashlib.sha256(token.encode()).hexdigest()[:16]
        self.assertLessEqual(auth.auth_cache[key]["expires_at"], expires)

        class AfterExpiration(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromtimestamp(expires + 1, tz=tz)

        with patch.object(auth, "datetime", AfterExpiration):
            self.assertEqual((await self.protected(token)).status_code, 401)
        self.assertNotIn(key, auth.auth_cache)

    async def test_challenge_client_has_no_unsigned_or_mock_auth_fallback(self):
        self.assertIsNone(supabase.auth.get_user("mock-token-123").user)
        self.assertIsNone(supabase.auth.get_user("invalid").user)
        self.assertIsNone(supabase.auth.get_user(self.token(exp=1)).user)
        self.assertIsNotNone(supabase.auth.get_user(self.token()).user)

    async def test_configured_supabase_login_verifies_password(self):
        verified_user = SimpleNamespace(
            id="real-user", email="real@example.com", user_metadata={},
            app_metadata={"tenant_id": "tenant-real", "role": "user"},
        )
        sign_in = Mock(return_value=SimpleNamespace(
            user=verified_user, session=SimpleNamespace(access_token="real-access-token"),
        ))
        login_client = SimpleNamespace(auth=SimpleNamespace(sign_in_with_password=sign_in))
        with patch.multiple(settings, supabase_url="https://example.supabase.co",
                            supabase_service_role_key="test-service-key"), \
             patch.object(login_module, "create_client", return_value=login_client):
            response = await self.client.post("/auth/login", json={
                "email": "real@example.com", "password": "exact-password",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["access_token"], "real-access-token")
            self.assertEqual(response.json()["user"]["tenant_id"], "tenant-real")
            sign_in.assert_called_once_with({
                "email": "real@example.com", "password": "exact-password",
            })
            sign_in.side_effect = ValueError("invalid password")
            response = await self.client.post("/auth/login", json={
                "email": "real@example.com", "password": "wrong",
            })
            self.assertEqual(response.status_code, 401)

    async def test_configured_supabase_tokens_are_revalidated_without_cache(self):
        verified_user = SimpleNamespace(
            id="real-user", email="real@example.com", user_metadata={},
            app_metadata={"tenant_id": "tenant-real", "role": "user"},
        )
        get_user = Mock(return_value=SimpleNamespace(user=verified_user))
        with patch.multiple(settings, supabase_url="https://example.supabase.co",
                            supabase_service_role_key="test-service-key"), \
             patch.object(supabase, "auth", SimpleNamespace(get_user=get_user)):
            response = await self.protected("supabase-verified-token")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["tenant_id"], "tenant-real")
            self.assertEqual(auth.auth_cache, {})
            get_user.side_effect = ValueError("expired token")
            self.assertEqual((await self.protected("supabase-verified-token")).status_code, 401)
            # A token signed with the local challenge key must not bypass a
            # configured Supabase authority either.
            self.assertEqual((await self.protected(self.token())).status_code, 401)
            self.assertEqual(get_user.call_count, 3)


if __name__ == "__main__":
    unittest.main()
