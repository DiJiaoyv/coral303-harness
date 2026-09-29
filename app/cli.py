"""Harness 管理 CLI 命令（create-admin 等）。"""
from __future__ import annotations

import getpass

import click
from flask.cli import with_appcontext

from app.models.user import User
from app.services.auth_service import (
    AuthConflictError,
    AuthValidationError,
    register_user,
    validate_password,
    validate_username,
)
from extensions import db


def _prompt_username(provided: str | None) -> str:
    while True:
        username = (provided or input("请输入管理员用户名: ")).strip()
        provided = None
        try:
            return validate_username(username)
        except AuthValidationError as exc:
            print(f"错误: {exc}")


def _prompt_password(provided: str | None) -> str:
    while True:
        if provided:
            password = provided
            provided = None
        else:
            password = getpass.getpass("请输入密码: ")
            confirm = getpass.getpass("请再次输入密码: ")
            if password != confirm:
                print("错误: 两次输入的密码不一致，请重试。")
                continue
        try:
            validate_password(password)
            return password
        except AuthValidationError as exc:
            print(f"错误: {exc}")


def create_admin_account(
    username: str | None = None,
    password: str | None = None,
) -> User:
    """创建或提升管理员账户。"""
    final_username = (
        validate_username(username) if username else _prompt_username(None)
    )
    if password:
        validate_password(password)
        final_password = password
    else:
        final_password = _prompt_password(None)

    existing = User.query.filter_by(username=final_username).first()
    if existing:
        existing.is_admin = True
        existing.is_active = True
        db.session.commit()
        user = existing
        print(f"已将现有用户 '{final_username}' 提升为管理员。")
    else:
        try:
            user = register_user(final_username, final_password)
        except AuthConflictError:
            raise SystemExit("错误: 用户名已存在")
        user.is_admin = True
        db.session.commit()
        print(f"管理员 {final_username} 创建成功")

    print("请勿将默认密码用于生产环境，请尽快修改密码。")
    return user


@click.command("create-admin")
@with_appcontext
def create_admin_command():
    """创建一个管理员用户（交互式输入，密码不回显）。"""
    create_admin_account()


def init_app(app):
    app.cli.add_command(create_admin_command)
