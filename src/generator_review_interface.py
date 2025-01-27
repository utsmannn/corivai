import os
from abc import ABC, abstractmethod
from src.models import ReviewResponse, ReviewComment
from openai import OpenAI, BaseModel
import json
from typing import List, Dict, Any


class ResponseReviewGenerator(ABC):
    @abstractmethod
    def generate(self, diff: str) -> ReviewResponse:
        """Generate review comments from diff content"""
        pass

class Comment(BaseModel):
  comment: str
  file_path: str
  line_string: str

class Response(BaseModel):
  response: list[Comment]


class AIReviewGenerator(ResponseReviewGenerator):
    def __init__(self, model_name: str):
        self.baseUrl = os.getenv('INPUT_OPEN-AI-URL')
        self.apiKey = os.getenv('API_KEY')
        self.client = OpenAI(base_url=self.baseUrl, api_key=self.apiKey)

        self.model_name = model_name

        # Define the response format for OpenAI
        self.response_format = {
            "type": "object",
            "properties": {
                "response": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "comment": {"type": "string"},
                            "file_path": {"type": "string"},
                            "line_string": {"type": "string"}
                        },
                        "required": ["comment", "file_path", "line_string"]
                    }
                }
            },
            "required": ["response"]
        }

    def generate(self, diff: str) -> ReviewResponse:
        response = self.client.beta.chat.completions.parse(
            model=self.model_name,
            response_format=Response,
            messages=[
                {
                    "role": "system",
                    "content": f"You are a code review assistant. Analyze the provided diff and generate review comments. Give me the comment, line string and **corrected** file path"
                },
                {
                    "role": "user",
                    "content": diff
                }
            ]
        )

        # Extract and parse the JSON response
        print(f"asuuu -> {response.choices[0].message}")
        result = json.loads(response.choices[0].message.content)

        # Create ReviewComment objects from the response
        comments = [
            ReviewComment(
                comment=item["comment"],
                file_path=item["file_path"],
                line_string=item["line_string"]
            )
            for item in result["response"]
        ]

        return ReviewResponse(comments=comments)