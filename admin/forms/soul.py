"""Soul 管理表单。"""
from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class SoulCoreForm(FlaskForm):
    name = StringField("角色名称", validators=[DataRequired(), Length(max=64)])
    role = StringField("角色定位", validators=[Optional(), Length(max=128)])
    core_traits = TextAreaField("核心特质（每行一条）", validators=[DataRequired()])
    core_drive = TextAreaField("核心驱动力", validators=[DataRequired(), Length(max=500)])
    fear = TextAreaField("核心恐惧", validators=[DataRequired(), Length(max=300)])
    catchphrases = TextAreaField("口头禅（每行一条）", validators=[Optional()])
    vocabulary = TextAreaField("专属词汇（每行一条）", validators=[Optional()])
    version = HiddenField()
    locked = BooleanField("核心已锁定", render_kw={"disabled": True})
    submit = SubmitField("保存核心")


class SoulStateForm(FlaskForm):
    arc_stage = SelectField("弧光阶段", validators=[DataRequired()])
    current_goal = TextAreaField("当前目标", validators=[DataRequired(), Length(max=500)])
    submit = SubmitField("保存状态")
