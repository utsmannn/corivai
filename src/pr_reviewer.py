import json
import logging
import re
import time
from typing import Dict, List, Tuple, Iterator

from src.exceptions import ReviewError
from src.generator_review_interface import AIReviewGenerator
from src.models import ReviewResponse
from .config import CorivaiConfig
from .git_interface import GitInterface

logger = logging.getLogger(__name__)


class PRReviewer:
    def __init__(self, git_interface: GitInterface, config: CorivaiConfig):

        self.git_interface = git_interface
        self.model_name = config.model_name
        self.max_diff_size = config.max_diff_size
        self.custom_instructions = config.custom_instruction
        self.chunk_size = 5
        self.chunk_delay = 5

        self.generator = AIReviewGenerator(config)

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

    def create_structured_diff(self, request, diff_content: str) -> Dict:
        structured_diff = {"diff": []}
        current_file = None
        diff_position = 0

        comments = self.git_interface.get_review_comments(request)

        existing_paths = [comment['path'] for comment in comments]
        existing_changes = [self._normalize_code(comment['diff_hunk']) for comment in comments]
        existing_positions = [comment['position'] for comment in comments]

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
                        line_num = diff_position + (block['start_line'] - i)

                        if (file_path not in existing_paths and
                                self._normalize_code(changes) not in existing_changes and
                                line_num not in existing_positions):
                            structured_diff["diff"].append({
                                "file_path": file_path,
                                "changes": changes,
                                "line": line_num,
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

    def process_chunk(self, chunk: Dict, request, current_head_sha: str) -> None:
        try:
            chunk_json = json.dumps(chunk, indent=2)
            review_response = self.generator.generate(chunk_json)

            comments = self.apply_review_comments(review_response, chunk, request)

            if comments:
                self.git_interface.create_review(request, comments)
                logger.info(f"Posted {len(comments)} comments for chunk")

        except Exception as e:
            logger.error(f"Error processing chunk: {str(e)}")
            return

    def validate_code_changes(self, request, file_path: str, line_content: str, position: int) -> bool:
        logger.info(f"anjay -------> start validating hunk")
        try:
            comments = self.git_interface.get_review_comments(request)
            normalized_content = self._normalize_code(line_content)
            logger.info(f"anjay -------> validating size: -> {len(comments)}")

            for comment in comments:
                logger.info(f"anjay -------> {comment['diff_hunk']}")

                if (comment['path'] == file_path and
                        comment['position'] == position and
                        self._normalize_code(comment['diff_hunk']) == normalized_content):
                    return False

            return True
        except Exception as e:
            logger.error(f"Error validating code changes: {str(e)}")
            return True

    def apply_review_comments(self, review_response: ReviewResponse, diff_chunk: Dict, request) -> List[dict]:
        comments = []

        for comment in review_response.comments:
            for diff_entry in diff_chunk["diff"]:
                if (diff_entry["file_path"] == comment.file_path and
                        self._normalize_code(diff_entry["changes"]) == self._normalize_code(comment.line_string)):

                    if diff_entry["line"] <= 0:
                        logger.warning(
                            f"Skipping comment for {comment.file_path}: Invalid position {diff_entry['line']}")
                        continue

                    if not self.validate_code_changes(request,
                                                      diff_entry["file_path"],
                                                      diff_entry["changes"],
                                                      diff_entry["line"]):
                        logger.info(
                            f"Skipping duplicate comment for {diff_entry['file_path']} at position {diff_entry['line']}")
                        continue

                    comments.append({
                        "path": comment.file_path,
                        "position": diff_entry["line"],
                        "body": f"**Finding**: {comment.comment}"
                    })
                    break

        return comments

    def _normalize_code(self, code: str) -> str:
        if not code:
            return ""
        return '\n'.join(line.strip() for line in str(code).split('\n') if line.strip())

    def process_request(self) -> None:
        try:
            request_number = self.git_interface.get_request_number()
            request = self.git_interface.get_request(request_number)
            current_head_sha = self.git_interface.get_head_sha(request)

            diff_content = self.git_interface.get_diff(request)
            if len(diff_content) > self.max_diff_size:
                logger.warning(f"Diff size ({len(diff_content)} bytes) exceeds limit")
                return

            structured_diff = self.create_structured_diff(request, diff_content)
            total_chunks = (len(structured_diff["diff"]) + self.chunk_size - 1) // self.chunk_size

            logger.info(f"Processing {len(structured_diff['diff'])} changes in {total_chunks} chunks")

            for i, chunk in enumerate(self.chunk_diff_data(structured_diff), 1):
                logger.info(f"Processing chunk {i}/{total_chunks}")
                self.process_chunk(chunk, request, current_head_sha)

                if i < total_chunks:
                    logger.debug(f"Waiting {self.chunk_delay} seconds before next chunk")
                    time.sleep(self.chunk_delay)

            self.git_interface.create_issue_comment(
                request,
                f"@corivai-review Last Processed SHA: {current_head_sha}\n"
                f"Review completed at: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            logger.info("Review completed successfully")

        except Exception as e:
            logger.error(f"Critical error in request review: {str(e)}")
            raise