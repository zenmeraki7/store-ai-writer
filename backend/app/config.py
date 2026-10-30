from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider_order: str = "ollama"

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.1-8b-instruct"
    nvidia_rpm: int = 35  # free tier is ~40 requests/min; stay under it

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "gemma3:4b"
    ollama_vision_model: str = ""  # leave empty to use ollama_model (gemma3 reads images)
    ollama_rpm: int = 600

    request_timeout: float = 90.0
    max_retries: int = 2  # re-asks the model when output fails validation


settings = Settings()
