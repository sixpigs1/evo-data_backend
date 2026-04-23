from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database (MySQL)
    DATABASE_URL: str = "mysql+pymysql://user:password@localhost:3306/evo_data?charset=utf8mb4"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # OSS
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET_NAME: str = "evo-data"
    OSS_ENDPOINT: str = "https://oss-cn-hangzhou.aliyuncs.com"
    OSS_BUCKET_DOMAIN: str = ""

    # STS
    STS_ROLE_ARN: str = ""
    STS_SESSION_NAME: str = "evo-data-session"
    STS_DURATION_SECONDS: int = 3600

    # Aliyun Region
    ALIYUN_REGION: str = "cn-hangzhou"

    # SMS（号码认证服务 Dypnsapi）
    SMS_ACCESS_KEY_ID: str = ""
    SMS_ACCESS_KEY_SECRET: str = ""
    # 使用号码认证服务平台赠送签名，必须从控制台赠送签名列表中选择
    SMS_SIGN_NAME: str = "速通互联验证码"
    # 赠送模板 Code（与阿里云号码认证服务控制台模板 CODE 一致）
    SMS_TEMPLATE_LOGIN: str = "100001"         # 登录/注册
    SMS_TEMPLATE_CHANGE_PHONE: str = "100002"  # 修改绑定手机号
    SMS_TEMPLATE_RESET_PASSWORD: str = "100003"  # 重置密码
    SMS_CODE_EXPIRE_MINUTES: int = 5           # 有效期（分钟），需与模板 ${min} 保持一致
    SMS_DEV_MODE: bool = True

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://data.evomind-tech.com"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    # Rate limits
    RATE_LIMIT_SMS: int = 5
    RATE_LIMIT_LOGIN: int = 10

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"


settings = Settings()
