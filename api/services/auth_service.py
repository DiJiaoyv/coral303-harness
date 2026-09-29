"""认证业务逻辑。"""
import re

from sqlalchemy.orm import Session

from api.utils.security import hash_password, verify_password
from database.models import User

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


class AuthValidationError(ValueError):
    pass


class AuthConflictError(Exception):
    pass


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_PATTERN.match(username):
        raise AuthValidationError("用户名须为 3–32 位字母、数字或下划线")
    return username


def validate_password(password: str) -> None:
    if not password or not PASSWORD_PATTERN.match(password):
        raise AuthValidationError("密码至少 8 位，且包含大写字母、小写字母和数字")


def register_user(db: Session, username: str, password: str) -> User:
    username = validate_username(username)
    validate_password(password)

    if db.query(User).filter(User.username == username).first():
        raise AuthConflictError("用户名已存在")

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    try:
        username = validate_username(username)
    except AuthValidationError:
        return None

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()
