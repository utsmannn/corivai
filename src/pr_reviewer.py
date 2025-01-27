import os
import logging
import re
import json
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
        print(f"\nurl repo ->\n{url}\n\n")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text

    def create_structured_diff(self, diff_content: str) -> Dict:
        """
        Create a structured diff for AI review.
        Returns a dictionary in the format:
        {
            "diff": [
                {
                    "file_path": str,
                    "changes": str,
                    "line": int,
                    "comment": ""
                }
            ]
        }
        """
        structured_diff = {"diff": []}
        current_file = None
        current_line = 0

        lines = diff_content.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            if line.startswith('diff --git'):
                match = re.match(r'diff --git a/(.+?) b/(.+)', line)
                if match:
                    current_file = match.group(2)
                i += 1
                continue

            if any(line.startswith(prefix) for prefix in ['index ', '--- ', '+++ ']):
                i += 1
                continue

            if line.startswith('@@'):
                match = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                if match:
                    current_line = int(match.group(1)) - 1
                i += 1
                continue

            if line.startswith('+') and not line.startswith('+++'):
                code_content = line[1:]
                if code_content.strip():
                    current_line += 1
                    structured_diff["diff"].append({
                        "file_path": current_file,
                        "changes": code_content.rstrip(),  # Remove trailing whitespace
                        "line": current_line,
                        "comment": ""
                    })
            elif line.startswith(' '):
                current_line += 1

            i += 1

        return structured_diff

    def apply_review_comments(self, review_response: ReviewResponse, structured_diff: Dict) -> List[dict]:
        """
        Convert review comments to GitHub comment format.
        """
        github_comments = []

        for comment in review_response.comments:
            # Find matching diff entry
            for diff_entry in structured_diff["diff"]:
                if (diff_entry["file_path"] == comment.file_path and
                        diff_entry["changes"].strip() == comment.line_string.strip()):
                    github_comments.append({
                        "path": comment.file_path,
                        "position": diff_entry["line"],
                        "body": f"**Finding**: {comment.comment}"
                    })
                    break

        return github_comments

    def post_comments(self, comments: List[dict], pr, current_head_sha: str) -> None:
        """Post the comments to GitHub PR."""
        if not comments:
            logger.info("No comments to post")
            return

        try:
            pr.create_review(event="COMMENT", comments=comments)
            pr.create_issue_comment(
                f"@corivai-review Last Processed SHA: {current_head_sha}")
            logger.info(f"Posted {len(comments)} review comments")
        except Exception as e:
            logger.error(f"Failed to post review comments: {str(e)}")
            raise

    def process_pr(self) -> None:
        """Main method to process a pull request."""
        try:
            # Get PR information
            pr_number = self.get_pr_number()
            pr = self.repo.get_pull(pr_number)
            current_head_sha = pr.head.sha

            # Check if already processed
            for comment in pr.get_issue_comments():
                if f"@corivai-review Last Processed SHA: {current_head_sha}" in comment.body:
                    logger.info("No new commits to process")
                    return

            # Get diff content
            diff_content = self.get_pr_diff(pr)
            if len(diff_content) > self.max_diff_size:
                logger.warning(f"Diff size ({len(diff_content)} bytes) exceeds limit")
                return

            # Create structured diff
            structured_diff = self.create_structured_diff(diff_content)

            # Log the structured diff for debugging
            logger.debug("Structured diff created:")
            logger.debug(json.dumps(structured_diff, indent=2))

            # Generate review using the AI generator
            review_response = self.generator.generate(json.dumps(structured_diff))

            # Convert review comments to GitHub format
            github_comments = self.apply_review_comments(review_response, structured_diff)

            # Post comments
            self.post_comments(github_comments, pr, current_head_sha)

            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise