from abc import ABC, abstractmethod
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content


class ResponseSummaryGenerator(ABC):
    @abstractmethod
    def generate(self, diff: str) -> str:
        """Generate review comments from diff content"""
        pass


class GeminiSummaryGenerator(ResponseSummaryGenerator):
    def __init__(self, model_name: str):
        self.generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_schema": content.Schema(
                type=content.Type.OBJECT,
                enum=[],
                required=["summary"],
                properties={
                    "summary": content.Schema(
                        type=content.Type.STRING,
                    ),
                },
            ),
            "response_mime_type": "application/json",
        }
        self.model = genai.GenerativeModel(model_name=model_name, generation_config=self.generation_config)

    def generate(self, diff: str) -> str:
        import json

        response = self.model.generate_content(diff)
        result = json.loads(response.text.strip().replace('```json', '').replace('```', ''))

        summary = result["summary"]

        return summary
