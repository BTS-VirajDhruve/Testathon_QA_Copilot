"""Admin user-management API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth_dependencies import require_admin_user
from app.models.auth import (
    InviteUserRequest,
    InviteUserResponse,
    UserCreateInput,
    UserPublic,
    UserUpdateInput,
)
from app.services.auth_service import AuthService, get_auth_service
from app.services.user_service import (
    UserAlreadyExistsError,
    UserNotFoundError,
    get_user_service,
)

router = APIRouter(tags=["users"], dependencies=[Depends(require_admin_user)])


def _map_user_create_error(exc: UserAlreadyExistsError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "USER_ALREADY_EXISTS", "message": str(exc)},
    )


def _map_user_not_found_error(exc: UserNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "USER_NOT_FOUND", "message": str(exc)},
    )


@router.get("/users", response_model=list[UserPublic])
@router.get("/auth/users", response_model=list[UserPublic])
async def list_users() -> list[UserPublic]:
    return await get_user_service().list_users()


@router.post("/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
@router.post(
    "/auth/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED
)
async def create_user(body: UserCreateInput) -> UserPublic:
    try:
        return await get_user_service().create_user(body)
    except UserAlreadyExistsError as exc:
        raise _map_user_create_error(exc) from exc


@router.post(
    "/users/invite",
    response_model=InviteUserResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/auth/users/invite",
    response_model=InviteUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_user(
    body: InviteUserRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> InviteUserResponse:
    try:
        return await auth_service.invite_user(body)
    except UserAlreadyExistsError as exc:
        raise _map_user_create_error(exc) from exc


async def _update_user(user_id: str, body: UserUpdateInput) -> UserPublic:
    try:
        return await get_user_service().update_user(user_id, body)
    except UserNotFoundError as exc:
        raise _map_user_not_found_error(exc) from exc


@router.patch("/users/{user_id}", response_model=UserPublic)
@router.patch("/auth/users/{user_id}", response_model=UserPublic)
async def patch_user(user_id: str, body: UserUpdateInput) -> UserPublic:
    return await _update_user(user_id, body)


@router.put("/users/{user_id}", response_model=UserPublic)
@router.put("/auth/users/{user_id}", response_model=UserPublic)
async def put_user(user_id: str, body: UserUpdateInput) -> UserPublic:
    return await _update_user(user_id, body)


@router.post("/users/{user_id}/deactivate", response_model=UserPublic)
@router.post("/auth/users/{user_id}/deactivate", response_model=UserPublic)
async def deactivate_user(user_id: str) -> UserPublic:
    return await _update_user(user_id, UserUpdateInput(isActive=False))


@router.delete("/users/{user_id}")
@router.delete("/auth/users/{user_id}")
async def delete_user(user_id: str) -> dict[str, bool]:
    deleted = await get_user_service().soft_delete_user(user_id)
    if not deleted:
        raise _map_user_not_found_error(UserNotFoundError("User not found"))
    return {"success": True}


@router.post("/users/{user_id}/soft-delete")
@router.post("/auth/users/{user_id}/soft-delete")
async def post_soft_delete_user(user_id: str) -> dict[str, bool]:
    return await delete_user(user_id)
