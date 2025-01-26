import os
import requests
import html
import base64
import logging
import re
from typing import Dict, List, Optional

from github import Github
from . import retry
from . import ReviewError
from . import ReviewResponse
from . import ResponseGenerator, GeminiGenerator

logger = logging.getLogger(__name__)


class PRReviewer:
    def __init__(self):
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.repo_name = os.getenv('GITHUB_REPOSITORY')
        self.model_name = os.getenv('INPUT_MODEL_NAME', 'gemini-1.5-pro-latest')
        self.max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '500000'))
        self.summary_text = f'## 📝 Code Review by Coriva.\nModel: ({self.model_name})'
        self.custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')

        if not all([self.github_token, self.repo_name]):
            raise ReviewError("Missing required environment variables")

        self.github = Github(self.github_token)
        self.repo = self.github.get_repo(self.repo_name)

        genai_api_key = os.getenv('GEMINI_API_KEY')
        if not genai_api_key:
            raise ReviewError("Missing Gemini API key")

        import google.generativeai as genai
        genai.configure(api_key=genai_api_key)
        self.generator = GeminiGenerator(self.model_name)

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
    def generate_review(self, diff: str) -> ReviewResponse:
        safe_diff = html.escape(diff[:self.max_diff_size])
        prompt = self._build_review_prompt(safe_diff)

        try:
            return self.generator.generate(prompt)
        except Exception as e:
            raise ReviewError(f"Failed to generate review: {str(e)}")

    def _build_review_prompt(self, diff: str) -> str:
        return f"""**Code Review Task**
Analyze this code diff and generate structured feedback:
{diff}

**Requirements:**
{self.custom_instructions}
"""

    def _find_position_in_diff(self, file_path: str, line_string: str, file_hunks: dict) -> Optional[int]:
        if file_path not in file_hunks:
            return None

        for hunk in file_hunks[file_path]:
            for i, line in enumerate(hunk['lines']):
                if line.strip() == line_string.strip():
                    return hunk['start_line'] + i
        return None

    @retry(max_retries=2, delay=3)
    def post_comments(self, review_response: ReviewResponse, pr, current_head_sha: str, diff_content: str) -> None:
        existing_comments = {(c.path, c.original_position) for c in pr.get_review_comments()}
        file_hunks = self.parse_diff(diff_content)
        comment_payload = []

        for comment in review_response.comments:
            file_path = comment.file_path
            line_string = comment.line_string

            file_lines = self.get_file_content(file_path, current_head_sha)
            if not file_lines:
                continue

            position = self._find_position_in_diff(file_path, line_string, file_hunks)
            if not position or (file_path, position) in existing_comments:
                continue

            comment_payload.append({
                "path": file_path,
                "position": position,
                "body": f"**Finding**: {comment.comment}"
            })

        if comment_payload:
            pr.create_review(event="COMMENT", comments=comment_payload)
            pr.create_issue_comment(f"@ai-reviewer Last Processed SHA: {current_head_sha}")
            logger.info(f"Posted {len(comment_payload)} new review comments")

    def process_pr(self) -> None:
        try:
            pr_number = self.get_pr_number()
            pr = self.repo.get_pull(pr_number)
            current_head_sha = pr.head.sha

            for comment in pr.get_issue_comments():
                if f"@ai-reviewer Last Processed SHA: {current_head_sha}" in comment.body:
                    logger.info("No new commits to process")
                    return

            diff_content = self.get_pr_diff(pr)
            if len(diff_content) > self.max_diff_size:
                logger.warning(f"Diff size ({len(diff_content)} bytes) exceeds limit")
                return

            review_response = self.generate_review(diff_content)
            self.post_comments(review_response, pr, current_head_sha, diff_content)
            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise