from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import audit, get_current_user
from app.models import User
from app.schemas import Token, UserOut
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == form.username.strip().lower()))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        audit(db, None, "login_failed", details={"email": form.username[:200]}, request=request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    audit(db, user, "login", request=request)
    db.commit()
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
