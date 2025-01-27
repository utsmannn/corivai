import os
import logging
import re
import html
import base64
from typing import Dict, List, Optional, Tuple

import requests
from github import Github

from src.exceptions import ReviewError
from src.models import ReviewResponse
from src.generator_review_interface import AIReviewGenerator
from src.decorators import retry

logger = logging.getLogger(__name__)


class PRReviewer:
    def __init__(self):
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.repo_name = os.getenv('GITHUB_REPOSITORY')
        self.model_name = os.getenv('INPUT_MODEL-NAME', '')
        self.max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '500000'))
        self.summary_text = f'## 📝 Code Review by Coriva.\nModel: ({self.model_name})'
        self.custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')

        if not all([self.github_token, self.repo_name]):
            raise ReviewError("Missing required environment variables")

        self.github = Github(self.github_token)
        self.repo = self.github.get_repo(self.repo_name)
        self.generator = AIReviewGenerator(self.model_name)

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

    def parse_diff(self, diff_content: str) -> Dict[str, dict]:
        """
        Parse git diff content into a structured format with line mapping.
        """
        file_hunks = {}
        current_file = None
        current_hunk = None
        line_map = {}  # Maps line content to file path and position

        for line in diff_content.split('\n'):
            if line.startswith('diff --git'):
                match = re.match(r'diff --git a/(.+?) b/(.+)', line)
                if match:
                    current_file = match.group(2)
                    file_hunks[current_file] = {
                        'hunks': [],
                        'content': []
                    }
            elif line.startswith('@@'):
                match = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', line)
                if match and current_file:
                    current_hunk = {
                        'start_line': int(match.group(1)),
                        'length': int(match.group(2)) if match.group(2) else 1,
                        'lines': [],
                        'header': line
                    }
                    file_hunks[current_file]['hunks'].append(current_hunk)
            elif current_file and current_hunk:
                if not line.startswith('---') and not line.startswith('+++'):
                    line_content = line[1:] if line.startswith(('+', '-', ' ')) else line
                    line_type = 'add' if line.startswith('+') else \
                        'remove' if line.startswith('-') else 'context'

                    # Calculate line number for added or context lines
                    line_number = None
                    if line_type in ('add', 'context'):
                        line_number = current_hunk['start_line'] + len([
                            l for l in current_hunk['lines']
                            if l.get('type') in ('add', 'context')
                        ])

                    line_info = {
                        'content': line_content,
                        'type': line_type,
                        'line_number': line_number
                    }
                    current_hunk['lines'].append(line_info)

                    # Map line content to file path and position for added lines
                    if line_type == 'add':
                        stripped_content = line_content.strip()
                        if stripped_content:  # Only map non-empty lines
                            if stripped_content not in line_map:
                                line_map[stripped_content] = []
                            line_map[stripped_content].append({
                                'file_path': current_file,
                                'position': line_number
                            })

        return file_hunks, line_map

    def find_line_locations(self, line_string: str, line_map: Dict[str, List[dict]]) -> List[Tuple[str, int]]:
        """
        Find all locations of a line string in the diff.
        """
        stripped_line = line_string.strip()
        locations = line_map.get(stripped_line, [])
        return [(loc['file_path'], loc['position']) for loc in locations]

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
Analyze this code diff and generate structured feedback. For each comment, provide:
1. The exact line of code you're commenting on (complete line, not partial)
2. Your review comment

Do not include file paths in your response - focus only on the specific lines and your comments about them.

Diff to review:
{diff}

**Requirements:**
{self.custom_instructions}
"""

    def _get_existing_comments(self, pr) -> set:
        return {(c.path, c.position) for c in pr.get_review_comments()}

    def process_review_comments(self, review_response: ReviewResponse,
                                line_map: Dict[str, List[dict]]) -> List[dict]:
        """
        Process review comments and map them to correct file locations.
        """
        processed_comments = []

        for comment in review_response.comments:
            locations = self.find_line_locations(comment.line_string, line_map)

            if not locations:
                logger.warning(f"No location found for line: {comment.line_string}")
                continue

            # Create a comment for each location where this line appears
            for file_path, position in locations:
                processed_comments.append({
                    'path': file_path,
                    'position': position,
                    'body': f"**Finding**: {comment.comment}"
                })

        return processed_comments

    def post_comments(self, comments: List[dict], pr, current_head_sha: str) -> None:
        """
        Post the processed comments to the PR.
        """
        existing_comments = self._get_existing_comments(pr)

        # Filter out existing comments
        new_comments = [
            comment for comment in comments
            if (comment['path'], comment['position']) not in existing_comments
        ]

        if new_comments:
            try:
                pr.create_review(event="COMMENT", comments=new_comments)
                pr.create_issue_comment(
                    f"@corivai-review Last Processed SHA: {current_head_sha}")
                logger.info(f"Posted {len(new_comments)} new review comments")
            except Exception as e:
                logger.error(f"Failed to post review comments: {str(e)}")
        else:
            logger.info("No new comments to post")

    def process_pr(self) -> None:
        """
        Main method to process a pull request.
        """
        try:
            pr_number = self.get_pr_number()
            pr = self.repo.get_pull(pr_number)
            current_head_sha = pr.head.sha

            # Check if already processed
            for comment in pr.get_issue_comments():
                if f"@corivai-review Last Processed SHA: {current_head_sha}" in comment.body:
                    logger.info("No new commits to process")
                    return

            # Get and validate diff content
            diff_content = self.get_pr_diff(pr)
            if len(diff_content) > self.max_diff_size:
                logger.warning(f"Diff size ({len(diff_content)} bytes) exceeds limit")
                return

            # Parse diff and generate review
            diff_data, line_map = self.parse_diff(diff_content)
            review_response = self.generate_review(diff_content)

            # Process and post comments
            processed_comments = self.process_review_comments(review_response, line_map)
            self.post_comments(processed_comments, pr, current_head_sha)

            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise