import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_REQUIRED_VARS = [
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_REGION",
    "BQ_DATASET",
    "FIVETRAN_API_KEY",
    "FIVETRAN_API_SECRET",
    "FIVETRAN_CONNECTOR_ID",
    "RAPIDAPI_KEY",
    "RAPIDAPI_HOST",
]


class Config:
    def __init__(self) -> None:
        missing = [k for k in _REQUIRED_VARS if not os.environ.get(k)]
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        self.PROJECT_ID: str = os.environ["GOOGLE_CLOUD_PROJECT"]
        self.REGION: str = os.environ["GOOGLE_CLOUD_REGION"]
        self.BQ_DATASET: str = os.environ["BQ_DATASET"]
        self.FIVETRAN_API_KEY: str = os.environ["FIVETRAN_API_KEY"]
        self.FIVETRAN_API_SECRET: str = os.environ["FIVETRAN_API_SECRET"]
        self.FIVETRAN_CONNECTOR_ID: str = os.environ["FIVETRAN_CONNECTOR_ID"]
        self.RAPIDAPI_KEY: str = os.environ["RAPIDAPI_KEY"]
        self.RAPIDAPI_HOST: str = os.environ["RAPIDAPI_HOST"]
        self.LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
        self.API_PORT: int = int(os.environ.get("API_PORT", "8000"))

    def table(self, table_name: str) -> str:
        """Return the fully-qualified BigQuery table ID for the given table name."""
        return f"{self.PROJECT_ID}.{self.BQ_DATASET}.{table_name}"


config = Config()
