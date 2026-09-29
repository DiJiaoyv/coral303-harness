"""创建角色向导：分步 WTForms 定义。"""
from __future__ import annotations

import re

from flask_wtf import FlaskForm
from wtforms import FloatField, IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, Regexp, ValidationError
from wtforms.validators import URL

NAME_RE = re.compile(r"^[\u4e00-\u9fa5a-zA-Z0-9_ ]{1,64}$")


class Step1Form(FlaskForm):
    name = StringField(
        "角色名称",
        validators=[
            DataRequired(message="请输入角色名称"),
            Length(min=1, max=64),
            Regexp(NAME_RE, message="名称仅允许中文、字母、数字、下划线和空格"),
        ],
    )
    description = TextAreaField(
        "角色描述",
        validators=[Optional(), Length(max=500, message="描述不超过 500 字符")],
    )
    avatar_url = StringField(
        "头像 URL",
        validators=[
            Optional(),
            Length(max=512),
            URL(require_tld=False, message="请输入合法的 URL"),
        ],
    )
    template_id = StringField("模板 ID", validators=[Optional(), Length(max=64)])
    next_btn = SubmitField("下一步")


class Step2Form(FlaskForm):
    system_prompt = TextAreaField(
        "系统提示词",
        validators=[
            DataRequired(message="请填写系统提示词"),
            Length(max=8192, message="系统提示词不超过 8192 字符"),
        ],
    )
    style_tags = StringField(
        "风格标签",
        validators=[Optional(), Length(max=256)],
        description="逗号分隔，如：冷酷,简洁,寡言",
    )
    next_btn = SubmitField("下一步")
    back_btn = SubmitField("上一步")


class Step3Form(FlaskForm):
    temperature = FloatField(
        "Temperature",
        validators=[DataRequired(), NumberRange(min=0.0, max=2.0)],
        default=0.7,
    )
    max_tokens = IntegerField(
        "Max Tokens",
        validators=[DataRequired(), NumberRange(min=64, max=8192)],
        default=2048,
    )
    top_p = FloatField(
        "Top P",
        validators=[DataRequired(), NumberRange(min=0.0, max=1.0)],
        default=0.9,
    )
    next_btn = SubmitField("下一步")
    back_btn = SubmitField("上一步")


class Step4Form(FlaskForm):
    world_id = SelectField(
        "世界观",
        choices=[("", "无")],
        validators=[Optional()],
    )
    owner_user_id = SelectField(
        "归属用户",
        coerce=int,
        validators=[Optional()],
    )
    next_btn = SubmitField("预览")
    back_btn = SubmitField("上一步")


class PreviewForm(FlaskForm):
    confirm_btn = SubmitField("确认创建")
    back_btn = SubmitField("返回修改")
