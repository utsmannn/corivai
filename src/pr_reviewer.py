import os
import logging
import re
import json
import time
from typing import Dict, List, Optional, Tuple, Iterator

import requests
from github import Github

from src.exceptions import ReviewError
from src.models import ReviewResponse, ReviewComment
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
        self.chunk_size = 5
        self.chunk_delay = 5  # seconds

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

    def extract_code_block(self, lines: List[str], start_idx: int, current_file: str) -> Tuple[str, int, List[dict]]:
        """
        Extract a complete code block starting from the given index.
        Returns the code block, the new index after the block, and the list of changed lines.
        """
        code_lines = []
        changed_blocks = []
        current_indent = None
        block_start_line = None
        current_block = []
        i = start_idx

        while i < len(lines):
            line = lines[i]

            # Stop if we hit a new diff or hunk header
            if line.startswith('diff --git') or line.startswith('@@'):
                break

            # Process the line based on its prefix
            if line.startswith('+'):
                content = line[1:]

                # Initialize or update indentation tracking
                line_indent = len(content) - len(content.lstrip())
                if current_indent is None and content.strip():
                    current_indent = line_indent

                # Check if this line belongs to the current block
                if content.strip():
                    if block_start_line is None:
                        block_start_line = i
                    current_block.append(content)
                elif current_block:
                    # Empty line within a block
                    current_block.append(content)
            elif line.startswith(' '):
                # Context line - if we had a block, save it
                if current_block:
                    block_text = '\n'.join(current_block)
                    if block_text.strip():  # Only save non-empty blocks
                        changed_blocks.append({
                            'file_path': current_file,
                            'changes': block_text,
                            'start_line': block_start_line
                        })
                    current_block = []
                    block_start_line = None
                    current_indent = None
            else:
                # For any other line (like removals), save the current block if exists
                if current_block:
                    block_text = '\n'.join(current_block)
                    if block_text.strip():
                        changed_blocks.append({
                            'file_path': current_file,
                            'changes': block_text,
                            'start_line': block_start_line
                        })
                    current_block = []
                    block_start_line = None
                    current_indent = None

            code_lines.append(line)
            i += 1

        # Add any remaining block
        if current_block:
            block_text = '\n'.join(current_block)
            if block_text.strip():
                changed_blocks.append({
                    'file_path': current_file,
                    'changes': block_text,
                    'start_line': block_start_line
                })

        return '\n'.join(code_lines), i, changed_blocks

    def create_structured_diff(self, diff_content: str) -> Dict:
        """
        Create a structured diff that includes complete code blocks.
        Returns a dictionary with detailed information about each changed block.
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

            if line.startswith('+') or line.startswith(' '):
                # Extract the complete code block and its changes
                _, new_idx, changed_blocks = self.extract_code_block(lines, i, current_file)

                # Add all changed blocks to the structured diff
                for block in changed_blocks:
                    if block['changes'].strip():
                        line_offset = block['start_line'] - i
                        structured_diff["diff"].append({
                            "file_path": block['file_path'],
                            "changes": block['changes'],
                            "line": current_line + line_offset + 1,
                            "comment": ""
                        })

                # Update line counter and index
                added_lines = new_idx - i
                current_line += added_lines
                i = new_idx
            else:
                i += 1

        return structured_diff

    def chunk_diff_data(self, diff_data: Dict[str, List[Dict]]) -> Iterator[Dict[str, List[Dict]]]:
        """
        Yield chunks of the diff data, each containing at most chunk_size items.
        """
        diff_items = diff_data["diff"]
        for i in range(0, len(diff_items), self.chunk_size):
            chunk = diff_items[i:i + self.chunk_size]
            yield {"diff": chunk}

    def process_chunks(self, structured_diff: Dict) -> List[ReviewResponse]:
        """
        Process the diff data in chunks, with delays between requests.
        """
        all_responses = []
        total_chunks = (len(structured_diff["diff"]) + self.chunk_size - 1) // self.chunk_size

        logger.info(f"Processing {len(structured_diff['diff'])} changes in {total_chunks} chunks")

        for i, chunk in enumerate(self.chunk_diff_data(structured_diff), 1):
            logger.info(f"Processing chunk {i}/{total_chunks}")

            try:
                # Convert chunk to JSON and generate review
                chunk_json = json.dumps(chunk, indent=2)
                review_response = self.generator.generate(chunk_json)
                all_responses.append(review_response)

                # Log chunk results
                logger.debug(f"Chunk {i} generated {len(review_response.comments)} comments")

                # Delay before next chunk unless it's the last one
                if i < total_chunks:
                    logger.debug(f"Waiting {self.chunk_delay} seconds before next chunk")
                    time.sleep(self.chunk_delay)

            except Exception as e:
                logger.error(f"Error processing chunk {i}: {str(e)}")
                raise

        return all_responses

    def merge_review_responses(self, responses: List[ReviewResponse]) -> ReviewResponse:
        """
        Merge multiple review responses into a single response.
        """
        all_comments = []
        for response in responses:
            all_comments.extend(response.comments)
        return ReviewResponse(comments=all_comments)

    def apply_review_comments(self, review_response: ReviewResponse, structured_diff: Dict) -> List[dict]:
        """
        Convert review comments to GitHub comment format.
        Matches comments with their corresponding locations in the diff.
        """
        github_comments = []

        for comment in review_response.comments:
            # Find matching diff entry using normalized comparison
            for diff_entry in structured_diff["diff"]:
                if (diff_entry["file_path"] == comment.file_path and
                        self._normalize_code(diff_entry["changes"]) == self._normalize_code(comment.line_string)):
                    github_comments.append({
                        "path": comment.file_path,
                        "position": diff_entry["line"],
                        "body": f"**Finding**: {comment.comment}"
                    })
                    break

        return github_comments

    def _normalize_code(self, code: str) -> str:
        """
        Normalize code string for comparison by removing extra whitespace and standardizing line endings.
        """
        return '\n'.join(line.strip() for line in code.split('\n') if line.strip())

    def post_comments(self, comments: List[dict], pr, current_head_sha: str) -> None:
        """Post the processed comments to the PR."""
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
        """
        Main method to process a pull request.
        Coordinates the entire review process from diff extraction to comment posting.
        """
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

            # Get and validate diff content
            diff_content = self.get_pr_diff(pr)
            if len(diff_content) > self.max_diff_size:
                logger.warning(f"Diff size ({len(diff_content)} bytes) exceeds limit")
                return

            # Create structured diff
            structured_diff = self.create_structured_diff(diff_content)

            # Process diff in chunks
            logger.info("Starting chunked review generation")
            review_responses = self.process_chunks(structured_diff)

            # Merge all responses
            merged_response = self.merge_review_responses(review_responses)

            # Convert to GitHub comments
            github_comments = self.apply_review_comments(merged_response, structured_diff)

            # Post comments
            self.post_comments(github_comments, pr, current_head_sha)

            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise