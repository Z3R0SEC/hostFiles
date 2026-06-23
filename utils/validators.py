"""
HostFlow — Validators
WTForms form classes used across the platform.
"""

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import (
    StringField, PasswordField, BooleanField, TextAreaField,
    SelectField, HiddenField, EmailField
)
from wtforms.validators import (
    DataRequired, Email, Length, EqualTo, Optional, Regexp
)


class RegisterForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    username = StringField("Username", validators=[
        DataRequired(), Length(min=3, max=30),
        Regexp(r"^[a-zA-Z0-9_]+$", message="Only letters, numbers, and underscores.")
    ])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField("Confirm Password", validators=[
        DataRequired(), EqualTo("password", message="Passwords must match.")
    ])
    cf_turnstile = HiddenField()


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    cf_turnstile = HiddenField()


class OTPForm(FlaskForm):
    code = StringField("OTP Code", validators=[
        DataRequired(), Length(min=6, max=6),
        Regexp(r"^\d{6}$", message="Must be a 6-digit number.")
    ])


class ForgotPasswordForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email()])
    cf_turnstile = HiddenField()


class ResetPasswordForm(FlaskForm):
    email = HiddenField(validators=[DataRequired()])
    code = StringField("OTP Code", validators=[DataRequired(), Length(min=6, max=6)])
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField("Confirm Password", validators=[
        DataRequired(), EqualTo("password")
    ])


class CreateSiteForm(FlaskForm):
    name = StringField("Website Name", validators=[DataRequired(), Length(min=2, max=80)])


class UploadSiteForm(FlaskForm):
    zip_file = FileField("Site ZIP", validators=[
        FileRequired(), FileAllowed(["zip"], "ZIP files only.")
    ])


class FileEditForm(FlaskForm):
    content = TextAreaField("Content")
    path = HiddenField()


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password = PasswordField("New Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField("Confirm", validators=[
        DataRequired(), EqualTo("new_password")
    ])


class ChangeEmailForm(FlaskForm):
    new_email = EmailField("New Email", validators=[DataRequired(), Email()])
    password = PasswordField("Your Password", validators=[DataRequired()])


class AdminUserForm(FlaskForm):
    role = SelectField("Role", choices=[
        ("user", "User"),
        ("support_agent", "Support Agent"),
        ("moderator", "Moderator"),
        ("admin", "Admin"),
        ("super_admin", "Super Admin"),
    ])
    is_verified = BooleanField("Verified")
    is_suspended = BooleanField("Suspended")
    is_banned = BooleanField("Banned")
    storage_limit_mb = StringField("Storage Limit (MB)")


class SystemSettingsForm(FlaskForm):
    platform_name = StringField("Platform Name", validators=[DataRequired()])
    maintenance_mode = BooleanField("Maintenance Mode")
    registration_enabled = BooleanField("Registration Enabled")
    default_storage_limit_mb = StringField("Default Storage (MB)")
    email_api_base = StringField("Email API Base URL")
    turnstile_site_key = StringField("Turnstile Site Key")
    turnstile_secret_key = StringField("Turnstile Secret Key")


class AnnouncementForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=200)])
    message = TextAreaField("Message", validators=[DataRequired()])
    type = SelectField("Type", choices=[
        ("info", "Info"), ("success", "Success"),
        ("warning", "Warning"), ("error", "Error")
    ])
