"""管理后台通用表单（原 admin/forms.py）。"""
import json
import re

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FloatField,
    HiddenField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

NAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff]{1,64}$", re.UNICODE)


class CharacterForm(FlaskForm):
    name = StringField(
        "角色名称",
        validators=[
            DataRequired(message="请输入角色名称"),
            Length(min=1, max=64, message="名称长度 1–64 字符"),
        ],
    )
    role = StringField(
        "角色定位",
        validators=[Optional(), Length(max=128)],
    )
    description = TextAreaField(
        "角色描述",
        validators=[Optional(), Length(max=1024, message="描述不超过 1024 字符")],
    )
    system_prompt = TextAreaField(
        "系统提示词",
        validators=[Optional(), Length(max=8192, message="系统提示不超过 8192 字符")],
    )
    temperature = FloatField(
        "Temperature",
        validators=[Optional(), NumberRange(min=0, max=2)],
        default=0.7,
    )
    max_tokens = IntegerField(
        "Max Tokens",
        validators=[Optional(), NumberRange(min=1, max=32000)],
        default=2048,
    )
    version = HiddenField()
    submit = SubmitField("保存")

    def validate_name(self, field):
        if not NAME_PATTERN.match(field.data or ""):
            raise ValidationError("名称只能包含字母、数字、下划线和中文")

    def parameters_dict(self) -> dict:
        return {
            "temperature": self.temperature.data if self.temperature.data is not None else 0.7,
            "max_tokens": self.max_tokens.data if self.max_tokens.data is not None else 2048,
        }

    def load_parameters(self, parameters_json: str | None) -> None:
        try:
            params = json.loads(parameters_json or "{}")
        except json.JSONDecodeError:
            params = {}
        self.temperature.data = params.get("temperature", 0.7)
        self.max_tokens.data = params.get("max_tokens", 2048)


class ArcStageForm(FlaskForm):
    new_stage = SelectField("弧光阶段", validators=[DataRequired()])
    submit = SubmitField("更新阶段")


class ArcGoalForm(FlaskForm):
    title = StringField(
        "目标标题",
        validators=[DataRequired(), Length(min=1, max=200)],
    )
    description = TextAreaField(
        "目标描述",
        validators=[Optional(), Length(max=1000)],
    )
    submit = SubmitField("添加目标")


class ArcGoalEditForm(FlaskForm):
    goal_id = HiddenField(validators=[DataRequired()])
    title = StringField(
        "目标标题",
        validators=[DataRequired(), Length(min=1, max=200)],
    )
    description = TextAreaField(
        "目标描述",
        validators=[Optional(), Length(max=1000)],
    )
    submit = SubmitField("保存修改")


class ArcAutoAdvanceForm(FlaskForm):
    auto_advance = BooleanField("允许自动推进")
    submit = SubmitField("保存设置")


class MemoryEditForm(FlaskForm):
    content = TextAreaField(
        "记忆内容",
        validators=[DataRequired(), Length(min=1, max=2000)],
    )
    importance = SelectField(
        "重要性",
        choices=[(str(i), f"{i} 星") for i in range(1, 6)],
        validators=[DataRequired()],
    )
    submit = SubmitField("保存")
