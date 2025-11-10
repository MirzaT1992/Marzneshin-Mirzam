"""
User Control Panel Routes

This module provides API endpoints for the user self-service portal,
allowing users to view their account information, get subscription links,
and manage their configs without admin assistance.
"""

import io
import logging
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import Response, HTMLResponse
import qrcode
import jwt

from app.config.env import DOCS_URL
from app.db import GetDB, crud
from app.db.models import User
from app.models.user_panel import (
    UserPanelAuth,
    UserPanelAuthResponse,
    UserPanelInfo,
    SubscriptionLinks,
)
from app.config import JWT_SECRET_KEY
from app.templates import render_template

logger = logging.getLogger(__name__)
router = APIRouter(tags=["User Panel"])

# JWT configuration for user panel tokens
USER_PANEL_TOKEN_EXPIRE_HOURS = 24


def create_user_panel_token(username: str, user_key: str) -> str:
    """
    Create JWT token for user panel access

    Args:
        username: Username
        user_key: User subscription key

    Returns:
        JWT token string
    """
    expire = datetime.utcnow() + timedelta(hours=USER_PANEL_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "key": user_key,
        "type": "user_panel",
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")


def verify_user_panel_token(token: str) -> dict:
    """
    Verify JWT token and return payload

    Args:
        token: JWT token string

    Returns:
        Token payload dict

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "user_panel":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user_panel_user(
    authorization: Annotated[str | None, Header()] = None
) -> User:
    """
    Get current user from JWT token

    Args:
        authorization: Authorization header with Bearer token

    Returns:
        User object

    Raises:
        HTTPException: If authentication fails
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header"
        )

    token = authorization.replace("Bearer ", "")
    payload = verify_user_panel_token(token)

    username = payload.get("sub")
    user_key = payload.get("key")

    with GetDB() as db:
        user = crud.get_user(db, username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify subscription key
        if user.key != user_key:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        return user


UserPanelUserDep = Annotated[User, Depends(get_current_user_panel_user)]


@router.get("/user-panel", response_class=HTMLResponse)
def user_panel_page():
    """
    Serve the user control panel HTML page

    This is the main entry point for users to access their self-service portal.
    Users can view account information, get subscription links, and download QR codes.

    **Access URL:** https://your-panel.com/user-panel
    """
    return render_template("user_panel.html")


@router.post("/api/user-panel/auth", response_model=UserPanelAuthResponse)
def authenticate_user(auth_request: UserPanelAuth):
    """
    Authenticate user with username and subscription key

    This endpoint allows users to log in to the user panel using their
    username and subscription key (found in their subscription URL).

    **Example:**
    ```json
    {
        "username": "john_doe",
        "subscription_key": "abc123def456..."
    }
    ```

    **Response:**
    Returns a JWT access token that should be included in the Authorization
    header for all subsequent requests:
    ```
    Authorization: Bearer <access_token>
    ```

    **Token Expiry:** 24 hours
    """
    with GetDB() as db:
        user = crud.get_user(db, auth_request.username)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Verify subscription key
        if user.key != auth_request.subscription_key:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Check if user is removed
        if user.removed:
            raise HTTPException(status_code=401, detail="Account has been removed")

        # Create access token
        access_token = create_user_panel_token(user.username, user.key)

        logger.info(f"User panel authentication successful for user: {user.username}")

        return UserPanelAuthResponse(
            access_token=access_token,
            token_type="bearer",
            username=user.username,
            expires_in=USER_PANEL_TOKEN_EXPIRE_HOURS * 3600
        )


@router.get("/api/user-panel/me", response_model=UserPanelInfo)
def get_my_info(user: UserPanelUserDep):
    """
    Get current user's account information

    Returns detailed information about the authenticated user's account,
    including traffic usage, expiry date, and account status.

    **Authentication:** Requires Bearer token from /auth endpoint
    """
    # Calculate remaining traffic
    remaining_traffic = None
    usage_percentage = None
    if user.data_limit:
        remaining_traffic = max(0, user.data_limit - user.used_traffic)
        usage_percentage = (user.used_traffic / user.data_limit) * 100

    # Calculate days remaining
    days_remaining = None
    if user.expire_date:
        delta = user.expire_date - datetime.utcnow()
        days_remaining = max(0, delta.days)

    return UserPanelInfo(
        username=user.username,
        is_active=user.is_active,
        expired=user.expired,
        data_limit_reached=user.data_limit_reached,
        used_traffic=user.used_traffic,
        data_limit=user.data_limit,
        remaining_traffic=remaining_traffic,
        usage_percentage=usage_percentage,
        expire_date=user.expire_date,
        expire_strategy=user.expire_strategy,
        days_remaining=days_remaining,
        created_at=user.created_at,
        enabled=user.enabled,
        activated=user.activated,
        services_count=len(user.services),
        note=user.note,
    )


@router.get("/api/user-panel/subscription-links", response_model=SubscriptionLinks)
def get_subscription_links(user: UserPanelUserDep):
    """
    Get subscription links for all client formats

    Returns subscription URLs for V2Ray, Clash, Clash Meta, and Sing-Box clients.

    **Authentication:** Requires Bearer token

    **Usage:**
    Copy the appropriate link for your client type and paste it into the
    client's subscription field.
    """
    base_url = DOCS_URL.rstrip('/')

    return SubscriptionLinks(
        v2ray=f"{base_url}/sub/{user.key}/links",
        clash=f"{base_url}/sub/{user.key}/clash",
        clash_meta=f"{base_url}/sub/{user.key}/clash-meta",
        singbox=f"{base_url}/sub/{user.key}/sing-box",
    )


@router.get("/api/user-panel/qr/{format}")
def get_qr_code(format: str, user: UserPanelUserDep):
    """
    Get QR code for subscription link

    Generates a QR code image for the specified subscription format.

    **Authentication:** Requires Bearer token

    **Parameters:**
    - `format`: Client format (v2ray, clash, clash-meta, singbox)

    **Response:** PNG image

    **Usage:**
    Scan the QR code with your mobile proxy client to automatically
    configure the subscription.
    """
    # Validate format
    valid_formats = {
        "v2ray": "links",
        "clash": "clash",
        "clash-meta": "clash-meta",
        "singbox": "sing-box",
    }

    if format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format. Must be one of: {', '.join(valid_formats.keys())}"
        )

    # Generate subscription URL
    base_url = DOCS_URL.rstrip('/')
    sub_url = f"{base_url}/sub/{user.key}/{valid_formats[format]}"

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(sub_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    logger.info(f"QR code generated for user {user.username}, format: {format}")

    return Response(content=img_bytes.read(), media_type="image/png")


@router.post("/api/user-panel/logout")
def logout(user: UserPanelUserDep):
    """
    Logout from user panel

    Note: Since JWT tokens are stateless, this endpoint simply confirms
    the logout action. The client should discard the token.

    **Authentication:** Requires Bearer token

    **Client Action:** Delete the stored access token after calling this endpoint.
    """
    logger.info(f"User {user.username} logged out from user panel")

    return {
        "message": "Logged out successfully",
        "username": user.username
    }
