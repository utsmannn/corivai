import os
import logging
import re
import html
import base64
from typing import Dict, List, Optional

import requests
from github import Github

from src.exceptions import ReviewError
from src.models import ReviewResponse
from src.generator_review_interface import AIReviewGenerator
from src.decorators import retry

logger = logging.getLogger(__name__)


class PRReviewer:
    def __init__(self):
        """Initialize the PR reviewer with configuration from environment variables."""
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
        """Extract PR number from GitHub reference."""
        pr_ref = os.getenv('GITHUB_REF')
        if not pr_ref:
            raise ReviewError("GITHUB_REF not found")
        try:
            return int(pr_ref.split('/')[-2])
        except (IndexError, ValueError) as e:
            raise ReviewError(f"Invalid PR reference format: {str(e)}")

    @retry(max_retries=3, delay=2)
    def get_pr_diff(self, pr) -> str:
        """Fetch the diff content for a PR using GitHub's API."""
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
        Parse git diff content into a structured format.

        Returns:
        Dict[str, dict]: A dictionary mapping file paths to their diff information
        """
        file_hunks = {}
        current_file = None
        current_hunk = None

        for line in diff_content.split('\n'):
            if line.startswith('diff --git'):
                match = re.match(r'diff --git a/(.+?) b/(.+)', line)
                if match:
                    current_file = match.group(2)
                    file_hunks[current_file] = {
                        'hunks': [],
                        'content': [],
                        'file_type': self._get_file_type(current_file)
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
                    line_info = {
                        'content': line[1:] if line.startswith((' ', '+', '-')) else line,
                        'type': 'add' if line.startswith('+') else
                        'remove' if line.startswith('-') else
                        'context',
                        'line_number': current_hunk['start_line'] + len([
                            l for l in current_hunk['lines']
                            if l.get('type') in ('add', 'context')
                        ]) if line.startswith(('+', ' ')) else None
                    }
                    current_hunk['lines'].append(line_info)
                    file_hunks[current_file]['content'].append(line)

        return file_hunks

    def _get_file_type(self, file_path: str) -> str:
        """Determine file type based on extension."""
        ext = os.path.splitext(file_path)[1].lower()
        return ext[1:] if ext else 'unknown'

    def get_file_content(self, file_path: str, ref: str) -> Optional[str]:
        """Fetch file content from GitHub repository."""
        try:
            response = requests.get(
                f"https://api.github.com/repos/{self.repo_name}/contents/{file_path}?ref={ref}",
                headers={'Authorization': f'Bearer {self.github_token}'}
            )
            response.raise_for_status()
            content = response.json()['content']
            return base64.b64decode(content).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to fetch file content: {str(e)}")
            return None

    def validate_and_map_comments(self, review_response: ReviewResponse, diff_data: Dict[str, dict]) -> List[dict]:
        """
        Validate AI review comments against diff data and map them to correct positions.
        """
        valid_comments = []

        for comment in review_response.comments:
            # Normalize and find matching file
            normalized_path = comment.file_path.lstrip('/')
            matching_files = [f for f in diff_data.keys()
                              if f.endswith(normalized_path) or normalized_path.endswith(f)]

            if not matching_files:
                logger.warning(f"No matching file found for AI comment: {comment.file_path}")
                continue

            file_path = matching_files[0]
            found_position = None

            # Find the correct position for the comment
            for hunk in diff_data[file_path]['hunks']:
                for line in hunk['lines']:
                    if (line['type'] == 'add' and
                            line['content'].strip() == comment.line_string.strip()):
                        found_position = line['line_number']
                        break
                if found_position:
                    break

            if found_position:
                valid_comments.append({
                    'path': file_path,
                    'position': found_position,
                    'body': f"**Finding**: {comment.comment}"
                })
            else:
                logger.warning(f"Could not find position for comment in {file_path}")

        return valid_comments

    @retry(max_retries=3, delay=2)
    def generate_review(self, diff: str) -> ReviewResponse:
        """Generate an AI review for the given diff content."""
        safe_diff = html.escape(diff[:self.max_diff_size])
        prompt = self._build_review_prompt(safe_diff)

        try:
            return self.generator.generate(prompt)
        except Exception as e:
            raise ReviewError(f"Failed to generate review: {str(e)}")

    def _build_review_prompt(self, diff: str) -> str:
        """Build the prompt for the AI review."""
        return f"""**Code Review Task**
Analyze this code diff and generate structured feedback:
{diff}

**Requirements:**
{self.custom_instructions}
"""

    def _get_existing_comments(self, pr) -> set:
        """Get existing review comments to avoid duplicates."""
        return {(c.path, c.position) for c in pr.get_review_comments()}

    def post_comments(self, review_response: ReviewResponse, pr, current_head_sha: str,
                      diff_data: Dict[str, dict]) -> None:
        """Post validated review comments to the PR."""
        existing_comments = self._get_existing_comments(pr)
        valid_comments = self.validate_and_map_comments(review_response, diff_data)

        # Filter out any comments that already exist
        new_comments = [
            comment for comment in valid_comments
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
        """Main method to process a pull request."""
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
            diff_data = self.parse_diff(diff_content)
            review_response = self.generate_review(diff_content)

            # Post comments
            self.post_comments(review_response, pr, current_head_sha, diff_data)
            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise