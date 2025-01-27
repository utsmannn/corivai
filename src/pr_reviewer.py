import json
import logging
import os
import re
import time
from typing import Dict, List, Tuple, Iterator

import requests
from github import Github
from github.PullRequest import PullRequest

from src.decorators import retry
from src.exceptions import ReviewError
from src.generator_review_interface import AIReviewGenerator
from src.models import ReviewResponse

logger = logging.getLogger(__name__)


class PRReviewer:
    def __init__(self):
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.repo_name = os.getenv('GITHUB_REPOSITORY')
        self.model_name = os.getenv('INPUT_MODEL-NAME', '')
        self.max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '500000'))
        self.custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')
        self.chunk_size = 5
        self.chunk_delay = 5

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

    def extract_code_block(self, lines: List[str], start_idx: int, current_file: str) -> Tuple[str, int, List[dict]]:
        code_lines = []
        changed_blocks = []
        i = start_idx
        block_start_line = None
        current_block = []

        while i < len(lines):
            line = lines[i]

            if line.startswith('diff --git') or line.startswith('@@'):
                break

            if line.startswith('+'):
                content = line[1:]
                if block_start_line is None:
                    block_start_line = i
                current_block.append(content)
            elif line.startswith(' '):
                if current_block:
                    changed_blocks.append({
                        'file_path': current_file,
                        'changes': '\n'.join(current_block),
                        'start_line': block_start_line
                    })
                    current_block = []
                    block_start_line = None
            else:
                if current_block:
                    changed_blocks.append({
                        'file_path': current_file,
                        'changes': '\n'.join(current_block),
                        'start_line': block_start_line
                    })
                    current_block = []
                    block_start_line = None

            code_lines.append(line)
            i += 1

        if current_block:
            changed_blocks.append({
                'file_path': current_file,
                'changes': '\n'.join(current_block),
                'start_line': block_start_line
            })

        return '\n'.join(code_lines), i, changed_blocks

    def create_structured_diff(self, pr: PullRequest, diff_content: str) -> Dict:
        structured_diff = {"diff": []}
        current_file = None
        diff_position = 0

        comments = pr.get_review_comments()

        existing_paths = [comment.path for comment in comments]
        existing_changes = [self._normalize_code(comment.diff_hunk) for comment in comments]
        existing_line = [comment.position for comment in comments]

        lines = diff_content.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            if line.startswith('diff --git'):
                match = re.match(r'diff --git a/(.+?) b/(.+)', line)
                if match:
                    current_file = match.group(2)
                    diff_position = 0
                i += 1
                continue

            if any(line.startswith(prefix) for prefix in ['index ', '--- ', '+++ ']):
                i += 1
                continue

            if line.startswith('@@'):
                diff_position += 1
                i += 1
                continue

            if line.startswith('+') or line.startswith(' '):
                _, new_idx, changed_blocks = self.extract_code_block(lines, i, current_file)

                for block in changed_blocks:
                    if block['changes'].strip():
                        file_path = block['file_path']
                        changes = block['changes']
                        line = diff_position + (block['start_line'] - i)

                        if file_path not in existing_paths and self._normalize_code(changes) not in existing_changes and line not in existing_line:
                            structured_diff["diff"].append({
                                "file_path": file_path,
                                "changes": changes,
                                "line": line,
                                "comment": ""
                            })

                diff_position += new_idx - i
                i = new_idx
            else:
                diff_position += 1
                i += 1

        return structured_diff

    def chunk_diff_data(self, diff_data: Dict[str, List[Dict]]) -> Iterator[Dict[str, List[Dict]]]:
        diff_items = diff_data["diff"]
        for i in range(0, len(diff_items), self.chunk_size):
            chunk = diff_items[i:i + self.chunk_size]
            yield {"diff": chunk}

    def process_chunk(self, chunk: Dict, pr, current_head_sha: str) -> None:
        try:
            chunk_json = json.dumps(chunk, indent=2)
            review_response = self.generator.generate(chunk_json)

            github_comments = self.apply_review_comments(review_response, chunk, pr)

            if github_comments:
                pr.create_review(
                    event="COMMENT",
                    comments=github_comments
                )
                logger.info(f"Posted {len(github_comments)} comments for chunk")

        except Exception as e:
            logger.error(f"Error processing chunk: {str(e)}")
            return

    def validate_code_changes(self, pr, file_path: str, line_content: str, position: int) -> bool:
        try:
            existing_reviews = pr.get_review_comments()
            normalized_content = self._normalize_code(line_content)

            for comment in existing_reviews:
                if (comment.path == file_path and
                        comment.position == position and
                        self._normalize_code(comment.diff_hunk) == normalized_content):
                    return False
            return True
        except Exception as e:
            logger.error(f"Error validating code changes: {str(e)}")
            return True

    def apply_review_comments(self, review_response: ReviewResponse, diff_chunk: Dict, pr) -> List[dict]:
        github_comments = []

        for comment in review_response.comments:
            for diff_entry in diff_chunk["diff"]:
                if (diff_entry["file_path"] == comment.file_path and
                        self._normalize_code(diff_entry["changes"]) == self._normalize_code(comment.line_string)):

                    if diff_entry["line"] <= 0:
                        logger.warning(
                            f"Skipping comment for {comment.file_path}: Invalid position {diff_entry['line']}")
                        continue

                    if not self.validate_code_changes(pr,
                                                      diff_entry["file_path"],
                                                      diff_entry["changes"],
                                                      diff_entry["line"]):
                        logger.info(
                            f"Skipping duplicate comment for {diff_entry['file_path']} at position {diff_entry['line']}")
                        continue

                    github_comments.append({
                        "path": comment.file_path,
                        "position": diff_entry["line"],
                        "body": f"**Finding**: {comment.comment}"
                    })
                    break

        return github_comments

    def _normalize_code(self, code: str) -> str:
        return '\n'.join(line.strip() for line in code.split('\n') if line.strip())

    def process_pr(self) -> None:
        try:
            pr_number = self.get_pr_number()
            pr = self.repo.get_pull(pr_number)
            current_head_sha = pr.head.sha

            diff_content = self.get_pr_diff(pr)
            if len(diff_content) > self.max_diff_size:
                logger.warning(f"Diff size ({len(diff_content)} bytes) exceeds limit")
                return

            structured_diff = self.create_structured_diff(pr, diff_content)
            total_chunks = (len(structured_diff["diff"]) + self.chunk_size - 1) // self.chunk_size

            logger.info(f"Processing {len(structured_diff['diff'])} changes in {total_chunks} chunks")

            for i, chunk in enumerate(self.chunk_diff_data(structured_diff), 1):
                logger.info(f"Processing chunk {i}/{total_chunks}")
                self.process_chunk(chunk, pr, current_head_sha)

                if i < total_chunks:
                    logger.debug(f"Waiting {self.chunk_delay} seconds before next chunk")
                    time.sleep(self.chunk_delay)

            pr.create_issue_comment(
                f"@corivai-review Last Processed SHA: {current_head_sha}\n"
                f"Review completed at: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in PR review: {str(e)}")
            raise
