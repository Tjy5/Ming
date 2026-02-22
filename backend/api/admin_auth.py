from __future__ import annotations

import hmac
import os
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Header, HTTPException

from models.game import ErrorResponse

load_dotenv()


def _admin_password() -> str:
    return (os.getenv("ADMIN_PASSWORD") or "").strip()


async def require_admin(
    x_admin_password: Annotated[str | None, Header(alias="X-Admin-Password")] = None,
) -> None:
    expected = _admin_password()
    if not expected:
        raise HTTPException(
            503,
            detail=ErrorResponse(
                error_code="admin_not_configured",
                message="ADMIN_PASSWORD 未配置",
            ).model_dump(),
        )

    submitted = (x_admin_password or "").strip()
    if not submitted or not hmac.compare_digest(submitted, expected):
        raise HTTPException(
            401,
            detail=ErrorResponse(
                error_code="admin_auth_failed",
                message="管理员认证失败",
            ).model_dump(),
        )

