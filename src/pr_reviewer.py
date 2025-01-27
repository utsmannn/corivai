import os
import logging
import re
import html
import json
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
        """Initialize the PR reviewer with required configuration."""
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.repo_name = os.getenv('GITHUB_REPOSITORY')
        self.model_name = os.getenv('INPUT_MODEL-NAME', '')
        self.max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '500000'))
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

    def parse_diff(self, diff_content: str) -> Dict:
        """
        Parse git diff content into structured JSON format.
        Returns a dictionary with 'diff' key containing list of file changes.
        """
        diff_data = {"diff": []}
        current_file = None
        current_changes = []

        lines = diff_content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith('diff --git'):
                # Add previous file's changes if they exist
                if current_file and current_changes:
                    diff_data["diff"].append({
                        "file_path": current_file,
                        "changes": '\n'.join(current_changes)
                    })
                    current_changes = []

                # Get new file path
                match = re.match(r'diff --git a/(.+?) b/(.+)', line)
                if match:
                    current_file = match.group(2)
                i += 1
                continue

            # Skip standard git diff headers
            if any(line.startswith(prefix) for prefix in ['index ', '--- ', '+++ ']):
                i += 1
                continue

            # Capture hunk headers and changes
            if line.startswith('@@') or line.startswith(' ') or line.startswith('+') or line.startswith('-'):
                current_changes.append(line)

            i += 1

        # Add the last file's changes
        if current_file and current_changes:
            diff_data["diff"].append({
                "file_path": current_file,
                "changes": '\n'.join(current_changes)
            })

        return diff_data

    def get_line_mapping(self, changes: str) -> Dict[str, List[int]]:
        """
        Create a mapping of lines to their positions in the file.
        """
        line_map = {}
        current_line = 0
        in_hunk = False

        for line in changes.split('\n'):
            if line.startswith('@@'):
                match = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                if match:
                    current_line = int(match.group(1)) - 1
                    in_hunk = True
                continue

            if not in_hunk:
                continue

            if line.startswith(' ') or line.startswith('+'):
                current_line += 1

            if line.startswith('+'):
                content = line[1:].strip()
                if content:
                    if content not in line_map:
                        line_map[content] = []
                    line_map[content].append(current_line)

        return line_map

    def find_line_position(self, target_line: str, file_changes: str) -> Optional[int]:
        """
        Find the position of a target line in the file changes.
        """
        line_map = self.get_line_mapping(file_changes)
        target_line = target_line.strip()

        return line_map.get(target_line, [None])[0]

    def process_review_comments(self, review_response: ReviewResponse, diff_data: Dict) -> List[dict]:
        """
        Process review comments using the JSON-structured diff data.
        """
        processed_comments = []

        for comment in review_response.comments:
            target_line = comment.line_string.strip()
            found_match = False

            for file_diff in diff_data['diff']:
                position = self.find_line_position(target_line, file_diff['changes'])

                if position is not None:
                    processed_comments.append({
                        'path': file_diff['file_path'],
                        'position': position,
                        'body': f"**Finding**: {comment.comment}"
                    })
                    found_match = True

            if not found_match:
                logger.warning(f"No match found for line: {target_line}")

        return processed_comments

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
Analyze this code diff and generate structured feedback. For each comment:
1. Include the EXACT line of code you're commenting on (only the code, without +/- prefixes)
2. Provide your review comment

Important: Copy the exact line from the diff, maintaining all whitespace and formatting.

Diff to review:
{diff}

**Requirements:**
{self.custom_instructions}"""

    def _get_existing_comments(self, pr) -> set:
        """Get existing review comments to avoid duplicates."""
        return {(c.path, c.position) for c in pr.get_review_comments()}

    def post_comments(self, comments: List[dict], pr, current_head_sha: str) -> None:
        """Post processed comments to the PR."""
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
                raise
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

            # Parse diff into JSON structure
            diff_data = self.parse_diff(diff_content)

            # Debug logging for diff structure
            logger.debug("Parsed diff structure:")
            logger.debug(json.dumps(diff_data, indent=2))

            # Generate review
            review_response = self.generate_review(str(diff_data))

            # Process and post comments
            processed_comments = self.process_review_comments(review_response, diff_data)

            # Post comments
            self.post_comments(processed_comments, pr, current_head_sha)

            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise