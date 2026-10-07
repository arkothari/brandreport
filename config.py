import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    tavily_api_key: str = ""
    db_path: str = "reports.db"
    pdf_dir: str = "pdfs"
    port: int = 8000


def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        db_path=os.getenv("DB_PATH", "reports.db"),
        pdf_dir=os.getenv("PDF_DIR", "pdfs"),
        port=int(os.getenv("PORT", "8000")),
    )


settings = get_settings()
