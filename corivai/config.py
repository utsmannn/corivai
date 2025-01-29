from pydantic import BaseModel

class CorivaiConfig(BaseModel):
    api_key: str
    openai_url: str
    model_name: str
    git_token: str
    max_diff_size: int
    custom_instruction: str