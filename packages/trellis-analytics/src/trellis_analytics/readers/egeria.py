"""Egeria reader: read only. Pieces 2a declares it; no routine in this release uses it.

It hands out pyegeria clients opened from an identity and offers no write method.
"""
from __future__ import annotations


class EgeriaReader:
    def __init__(self, view_server: str, platform_url: str, user_id: str, user_pwd: str | None = None):
        self.view_server, self.platform_url, self.user_id, self._pwd = view_server, platform_url, user_id, user_pwd

    def client(self, client_class):
        """Open `client_class` (a pyegeria client) for reading. The caller must not call its write methods."""
        c = client_class(self.view_server, self.platform_url, user_id=self.user_id, user_pwd=self._pwd)
        c.create_egeria_bearer_token(self.user_id, self._pwd)
        return c
