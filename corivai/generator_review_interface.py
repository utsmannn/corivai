import json
from abc import ABC, abstractmethod
from typing import Dict

from openai import OpenAI, BaseModel

from corivai.config import CorivaiConfig
from corivai.models import ReviewResponse, ReviewComment


class ResponseReviewGenerator(ABC):
    @abstractmethod
    def generate(self, diff: str) -> ReviewResponse:
        pass

class DiffItem(BaseModel):
    file_path: str
    changes: str
    line: int
    comment: str

class DiffResponse(BaseModel):
    diff: list[DiffItem]

class AIReviewGenerator(ResponseReviewGenerator):
    def __init__(self, config: CorivaiConfig):

        # self.baseUrl = os.getenv('INPUT_OPENAI-URL', 'https://api.openai.com/v1')
        # self.apiKey = os.getenv('API_KEY')

        self.client = OpenAI(base_url=config.openai_url, api_key=config.api_key)
        self.model_name = config.model_name

    def generate(self, structured_diff: str) -> ReviewResponse:
        response = self.client.beta.chat.completions.parse(
            model=self.model_name,
            response_format=DiffResponse,
            messages=[
                {
                    "role": "system",
                    "content": """You are a code review assistant. Review the provided structured diff and add comments where appropriate.
                    - Keep the exact same JSON structure
                    - Add your review comments in the 'comment' field
                    - Leave 'comment' empty if no issues are found
                    - Do not modify file_path, changes, or line fields
                    - Provide specific, actionable feedback"""
                },
                {
                    "role": "user",
                    "content": structured_diff
                }
            ],
            temperature=0.2,
            top_p=0.95
        )

        try:
            diff_response = json.loads(response.choices[0].message.content)

            comments = [
                ReviewComment(
                    comment=item["comment"],
                    file_path=item["file_path"],
                    line_string=item["changes"]
                )
                for item in diff_response["diff"]
                if item["comment"]
            ]

            return ReviewResponse(comments=comments)

        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            raise ValueError(f"Failed to parse AI response: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing AI response: {str(e)}")

    def _validate_response(self, response_data: Dict) -> bool:
        if not isinstance(response_data, dict) or "diff" not in response_data:
            return False

        for item in response_data["diff"]:
            required_fields = {"file_path", "changes", "line", "comment"}
            if not all(field in item for field in required_fields):
                return False

            if not isinstance(item["line"], int):
                return False

        return True