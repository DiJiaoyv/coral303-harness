import re

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp

from app.services.auth_service import (
    AuthConflictError,
    AuthValidationError,
    authenticate_user,
    register_user,
    validate_password,
    validate_username,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

PASSWORD_REGEX = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


class RegisterForm(FlaskForm):
    username = StringField(
        "用户名",
        validators=[
            DataRequired(),
            Length(min=3, max=32),
            Regexp(r"^[a-zA-Z0-9_]+$", message="只允许字母、数字、下划线"),
        ],
    )
    password = PasswordField("密码", validators=[DataRequired(), Length(min=8)])
    submit = SubmitField("注册")


class LoginForm(FlaskForm):
    username = StringField(
        "用户名",
        validators=[
            DataRequired(),
            Length(min=3, max=32),
            Regexp(r"^[a-zA-Z0-9_]+$"),
        ],
    )
    password = PasswordField("密码", validators=[DataRequired()])
    submit = SubmitField("登录")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("data.index"))

    form = RegisterForm()
    error = None

    if request.method == "POST":
        if request.is_json:
            data = request.get_json(silent=True) or {}
            username = data.get("username", "")
            password = data.get("password", "")
            try:
                validate_username(username)
                validate_password(password)
                user = register_user(username, password)
                return jsonify(user.to_public_dict()), 201
            except AuthConflictError:
                return jsonify({"error": "用户名已存在"}), 409
            except AuthValidationError as exc:
                return jsonify({"error": str(exc)}), 400

        if form.validate_on_submit():
            try:
                if not PASSWORD_REGEX.match(form.password.data or ""):
                    error = "密码至少 8 位，且包含大写字母、小写字母和数字"
                else:
                    register_user(form.username.data, form.password.data)
                    return redirect(url_for("auth.login"))
            except AuthConflictError:
                error = "用户名已存在"
            except AuthValidationError as exc:
                error = str(exc)
        else:
            error = "请检查表单输入"

    return render_template("register.html", form=form, error=error)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("data.index"))

    form = LoginForm()
    error = None

    if request.method == "POST":
        if request.is_json:
            data = request.get_json(silent=True) or {}
            user = authenticate_user(
                data.get("username", ""), data.get("password", "")
            )
            if user:
                login_user(user, remember=True)
                return jsonify(user.to_public_dict()), 200
            return jsonify({"error": "用户名或密码错误"}), 401

        if form.validate_on_submit():
            user = authenticate_user(form.username.data, form.password.data)
            if user:
                login_user(user, remember=True)
                next_page = request.args.get("next")
                return redirect(next_page or url_for("data.index"))
            error = "用户名或密码错误"

    return render_template("login.html", form=form, error=error)


@auth_bp.route("/logout", methods=["GET"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    return jsonify(current_user.to_public_dict())
