from abc import ABC, abstractmethod
from src import *


class ResponseGenerator(ABC):
    @abstractmethod
    def generate(self, diff: str) -> ReviewResponse:
        """Generate review comments from diff content"""
        pass


class GeminiGenerator(ResponseGenerator):
    def __init__(self, model_name: str):
        import google.generativeai as genai
        from google.ai.generativelanguage_v1beta.types import content

        self.generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_schema": content.Schema(
                type=content.Type.OBJECT,
                properties={
                    "response": content.Schema(
                        type=content.Type.ARRAY,
                        items=content.Schema(
                            type=content.Type.OBJECT,
                            properties={
                                "comment": content.Schema(type=content.Type.STRING),
                                "file_path": content.Schema(type=content.Type.STRING),
                                "line_string": content.Schema(type=content.Type.STRING),
                            },
                            required=["comment", "file_path", "line_string"]
                        )
                    )
                },
                required=["response"]
            ),
            "response_mime_type": "application/json",
        }
        self.model = genai.GenerativeModel(model_name=model_name, generation_config=self.generation_config)

    def generate(self, diff: str) -> ReviewResponse:
        import json

        response = self.model.generate_content(diff)
        result = json.loads(response.text.strip().replace('```json', '').replace('```', ''))

        comments = [
            ReviewComment(
                comment=item["comment"],
                file_path=item["file_path"],
                line_string=item["line_string"]
            )
            for item in result["response"]
        ]

        return ReviewResponse(comments=comments)