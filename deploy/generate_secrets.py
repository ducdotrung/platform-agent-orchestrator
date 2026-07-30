"""Generate ignored, owner-readable secrets for the disposable local sample."""

from __future__ import annotations

import secrets
from pathlib import Path

TARGET = Path(".local-secrets")


def main() -> None:
    TARGET.mkdir(mode=0o700, exist_ok=True)
    for name in ("database_password", "webhook_signing_secret", "reviewer_signing_secret"):
        path = TARGET / name
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48) + "\n")
            path.chmod(0o600)
        elif path.stat().st_mode & 0o077:
            raise PermissionError(f"secret must not be group/world accessible: {path}")


if __name__ == "__main__":
    main()
