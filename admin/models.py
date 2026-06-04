from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3)
    keyword: str = Field(..., min_length=1, max_length=50)
    active: bool = True
    use_email: bool = True
    use_whatsapp: bool = True
    fetch_calendar: bool = False
    max_email_results: Optional[int] = Field(None, ge=1, le=100)
    days_threshold: Optional[int] = Field(None, ge=1, le=30)
    schedule_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    smtp_host_user: Optional[str] = None
    smtp_host_password: Optional[str] = None
    mobile: Optional[str] = Field(None, pattern=r"^\d{10,15}$")

    @field_validator("keyword")
    @classmethod
    def keyword_valid(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("Keyword must be alphanumeric (dash/underscore allowed)")
        return v


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[str] = Field(None, min_length=3)
    active: Optional[bool] = None
    use_email: Optional[bool] = None
    use_whatsapp: Optional[bool] = None
    fetch_calendar: Optional[bool] = None
    max_email_results: Optional[int] = Field(None, ge=1, le=100)
    days_threshold: Optional[int] = Field(None, ge=1, le=30)
    schedule_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    smtp_host_user: Optional[str] = None
    smtp_host_password: Optional[str] = None
    mobile: Optional[str] = Field(None, pattern=r"^\d{10,15}$")


class ActionRequest(BaseModel):
    keyword: Optional[str] = None
    days: int = Field(2, ge=1, le=30)
    max_results: int = Field(20, ge=1, le=100)


class ModelSwitchRequest(BaseModel):
    provider: str
    model_name: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0, le=2)


class TestEmailRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class TestWhatsAppRequest(BaseModel):
    mobile: str = Field(..., pattern=r"^\d{10,15}$")
    message: str = Field(..., min_length=1)
