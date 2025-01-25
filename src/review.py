import os
from functools import wraps

import requests
import json
import time
import html
import base64
import logging
from typing import Dict, List, Optional
from github import Github, GithubException
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReviewError(Exception):
    """Custom exception for review-related errors"""
    pass


def retry(max_retries=3, delay=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Final retry failed for {func.__name__}: {str(e)}")
                        raise
                    logger.warning(f"Attempt {attempt + 1} failed, retrying...")
                    time.sleep(delay * (2 ** attempt))
            return func(*args, **kwargs)

        return wrapper

    return decorator


class PRReviewer:
    def __init__(self):
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.repo_name = os.getenv('GITHUB_REPOSITORY')
        self.model_name = os.getenv('INPUT_MODEL_NAME', 'gemini-1.5-pro-latest')
        self.max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '100000'))
        self.footer_text = os.getenv('INPUT_FOOTER_TEXT', 'AI Code Review Report')
        self.custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')

        if not all([self.github_token, self.repo_name]):
            raise ReviewError("Missing required environment variables")

        self.github = Github(self.github_token)
        self.repo = self.github.get_repo(self.repo_name)

        # Configure Gemini
        genai_api_key = os.getenv('GEMINI_API_KEY')
        if not genai_api_key:
            raise ReviewError("Missing Gemini API key")
        genai.configure(api_key=genai_api_key)

    def get_pr_number(self) -> int:
        pr_ref = os.getenv('GITHUB_REF')
        if not pr_ref:
            raise ReviewError("GITHUB_REF not found")
        try:
            return int(pr_ref.split('/')[-2])
        except (IndexError, ValueError) as e:
            raise ReviewError(f"Invalid PR reference format: {str(e)}")

    @retry(max_retries=3, delay=2)
    def get_pr_diff(self, pr) -> str:
        headers = {
            'Authorization': f'Bearer {self.github_token}',
            'Accept': 'application/vnd.github.v3.diff'
        }
        url = f'https://api.github.com/repos/{self.repo_name}/pulls/{pr.number}'

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text

    def parse_diff(self, diff_content: str) -> Dict[str, List[dict]]:
        file_hunks = {}
        current_file = None

        for line in diff_content.split('\n'):
            if line.startswith('diff --git'):
                match = re.match(r'diff --git a/(.+?) b/(.+)', line)
                if match:
                    current_file = match.group(2)
                    file_hunks[current_file] = []
            elif line.startswith('@@'):
                match = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', line)
                if match:
                    file_hunks[current_file].append({
                        'start_line': int(match.group(1)),
                        'lines': []
                    })
            elif current_file and file_hunks[current_file]:
                if line.startswith('+') and not line.startswith('+++'):
                    file_hunks[current_file][-1]['lines'].append(line[1:].rstrip('\n'))

        return file_hunks

    def get_file_content(self, file_path: str, ref: str) -> Optional[List[str]]:
        try:
            response = requests.get(
                f"https://api.github.com/repos/{self.repo_name}/contents/{file_path}?ref={ref}",
                headers={'Authorization': f'Bearer {self.github_token}'}
            )
            response.raise_for_status()
            content = response.json()['content']
            return base64.b64decode(content).decode('utf-8').splitlines()
        except Exception as e:
            logger.error(f"Failed to fetch file content: {str(e)}")
            return None

    @retry(max_retries=3, delay=2)
    def generate_review(self, diff: str) -> dict:
        generation_config = {
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
                    ),
                    "summary_advice": content.Schema(type=content.Type.STRING),
                },
                required=["response", "summary_advice"]
            ),
            "response_mime_type": "application/json",
        }

        model = genai.GenerativeModel(
            model_name=self.model_name,
            generation_config=generation_config
        )

        safe_diff = html.escape(diff[:50000])
        prompt = self._build_review_prompt(safe_diff)

        try:
            response = model.generate_content(prompt)
            result = json.loads(response.text.strip().replace('```json', '').replace('```', ''))
            self._validate_review_response(result)
            return result
        except Exception as e:
            raise ReviewError(f"Failed to generate review: {str(e)}")

    def _build_review_prompt(self, diff: str) -> str:
        return f"""**Code Review Task**
Analyze this code diff and generate structured feedback:
{diff}

**Requirements:**
{self.custom_instructions}
"""

    def _validate_review_response(self, result: dict) -> None:
        if not all(key in result for key in ['response', 'summary_advice']):
            raise ReviewError("Invalid response structure")

        for comment in result['response']:
            if not all(k in comment for k in ['comment', 'file_path', 'line_string']):
                raise ReviewError("Invalid comment format")

    @retry(max_retries=2, delay=3)
    def post_comments(self, comments: list, pr, current_head_sha: str, diff_content: str) -> None:
        existing_comments = {(c.path, c.original_position) for c in pr.get_review_comments()}
        file_hunks = self.parse_diff(diff_content)
        comment_payload = []

        for comment in comments:
            file_path = comment['file_path']
            line_string = comment['line_string']

            file_lines = self.get_file_content(file_path, current_head_sha)
            if not file_lines:
                continue

            position = self._find_position_in_diff(file_path, line_string, file_hunks)
            if not position or (file_path, position) in existing_comments:
                continue

            comment_payload.append({
                "path": file_path,
                "position": position,
                "body": f"**Finding**: {comment['comment']}"
            })

        if comment_payload:
            pr.create_review(event="COMMENT", comments=comment_payload)
            pr.create_issue_comment(f"@ai-reviewer Last Processed SHA: {current_head_sha}")
            logger.info(f"Posted {len(comment_payload)} new review comments")

    def _find_position_in_diff(self, file_path: str, line_string: str, file_hunks: dict) -> Optional[int]:
        if file_path not in file_hunks:
            return None

        for hunk in file_hunks[file_path]:
            for i, line in enumerate(hunk['lines']):
                if line.strip() == line_string.strip():
                    return hunk['start_line'] + i
        return None

    @retry(max_retries=2, delay=3)
    def post_summary(self, summary: str, pr) -> None:
        pr.create_issue_comment(f"## 📝 {self.footer_text}\n\n{summary}")

    def process_pr(self) -> None:
        try:
            pr_number = self.get_pr_number()
            pr = self.repo.get_pull(pr_number)
            current_head_sha = pr.head.sha

            # Check if already processed
            for comment in pr.get_issue_comments():
                if f"@ai-reviewer Last Processed SHA: {current_head_sha}" in comment.body:
                    logger.info("No new commits to process")
                    return

            diff_content = self.get_pr_diff(pr)
            if len(diff_content) > self.max_diff_size:
                logger.warning(f"Diff size ({len(diff_content)} bytes) exceeds limit")
                return

            review_data = self.generate_review(diff_content)
            self.post_summary(review_data['summary_advice'], pr)
            self.post_comments(review_data['response'], pr, current_head_sha, diff_content)

            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise


def main():
    try:
        reviewer = PRReviewer()
        reviewer.process_pr()
    except Exception as e:
        logger.error(f"Failed to complete review: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()