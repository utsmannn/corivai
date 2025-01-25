import os
import requests
import json
import time
import html
import base64
from github import Github
import google.generativeai as genai
from google.ai.generativelanguage_v1beta.types import content
from functools import wraps
import re


def retry(max_retries=3, delay=2):
    """Retry decorator with exponential backoff"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                    time.sleep(delay ** retries)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_pr_number() -> int:
    """Retrieve the PR number from environment variables"""
    pr_ref = os.getenv('GITHUB_REF', '')
    if not pr_ref:
        raise ValueError("Environment variable GITHUB_REF not found.")
    pr_num = pr_ref.split('/')[-2]
    return int(pr_num)


def sanitize_input(text: str, max_length=2000) -> str:
    """Sanitize and truncate user input"""
    return html.escape(text[:max_length]) if text else ""


@retry(max_retries=3, delay=2)
def get_pr_diff(pr) -> str:
    """Retrieve PR diff from GitHub API"""
    try:
        # Mendapatkan diff dalam format string
        diff_content = pr.get_diff()
        return diff_content
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch PR diff: {str(e)}")


@retry(max_retries=3, delay=2)
def generate_review(diff: str, model_name: str, custom_instructions: str) -> dict:
    """Generate structured code review using Gemini"""
    print("diff:")
    print(diff)
    print("diff===")
    try:
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

        generation_config = {
            "temperature": 1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
            "response_schema": content.Schema(
                type=content.Type.OBJECT,
                enum=[],
                required=["response", "summary_advice"],
                properties={
                    "response": content.Schema(
                        type=content.Type.ARRAY,
                        items=content.Schema(
                            type=content.Type.OBJECT,
                            enum=[],
                            required=["comment", "file_path", "line_string"],
                            properties={
                                "comment": content.Schema(
                                    type=content.Type.STRING,
                                ),
                                "file_path": content.Schema(
                                    type=content.Type.STRING,
                                ),
                                "line_string": content.Schema(
                                    type=content.Type.STRING,
                                ),
                            },
                        ),
                    ),
                    "summary_advice": content.Schema(
                        type=content.Type.STRING,
                    ),
                },
            ),
            "response_mime_type": "application/json",
        }

        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=generation_config,
            system_instruction="You are a git diff analyzer that provides line-by-line code reviews."
        )

        safe_diff = sanitize_input(diff, 50000)
        instructions = sanitize_input(custom_instructions)

        prompt = f"""**Code Review Task**
Analyze this code diff and generate structured feedback:
{safe_diff}

**Requirements:**
{instructions}
- Example: 
{{
  "response": [
    {{
      "comment": "Potential SQL injection",
      "file_path": "src/db.py",
      "line_string": "query = f\"SELECT * FROM users WHERE id = user_id\""
    }}
  ],
  "summary_advice": "Overall recommendations"
}}"""
        response = model.generate_content(prompt)
        raw_json = response.text.strip().replace('```json', '').replace('```', '')

        # Validate JSON structure
        result = json.loads(raw_json)
        print("result:")
        print(result)
        print("result====")

        # Validate that required fields exist
        if not all(key in result for key in ['response', 'summary_advice']):
            raise ValueError("Invalid response structure")

        for comment in result['response']:
            if not all(k in comment for k in ['comment', 'file_path', 'line_string']):
                raise ValueError("Invalid comment format")

        return result

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Review generation failed: {str(e)}")


@retry(max_retries=2, delay=3)
def post_comment(comments: list, pr, repo_name, github_token, current_head_sha, diff_content):
    """Post review comments by finding accurate positions based on line_string and avoiding duplicates"""
    try:
        # Fetch existing review comments to prevent duplicates
        existing_review_comments = pr.get_review_comments()
        existing_comments_set = set()
        for comment in existing_review_comments:
            existing_comments_set.add((comment.path, comment.original_position))

        comment_payload = []

        # Parsing the diff to map line_number to position
        # Note: Mapping line_number to position in diff is non-trivial
        # Berikut adalah pendekatan sederhana yang mungkin tidak 100% akurat

        # Membuat mapping file_path ke hunk informasi
        file_hunks = {}
        current_file = None
        current_hunk = None

        diff_lines = diff_content.split('\n')
        for line in diff_lines:
            if line.startswith('diff --git'):
                match = re.match(r'diff --git a/(.+?) b/(.+)', line)
                if match:
                    current_file = match.group(2)
                    file_hunks[current_file] = []
            elif line.startswith('@@'):
                match = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', line)
                if match:
                    start_line = int(match.group(1))
                    file_hunks[current_file].append({
                        'start_line': start_line,
                        'lines': []
                    })
            elif current_file and current_hunk:
                if line.startswith('+') and not line.startswith('+++'):
                    file_hunks[current_file][-1]['lines'].append(line[1:].rstrip('\n'))
                elif line.startswith('-') and not line.startswith('---'):
                    pass  # Removed lines
                elif line.startswith(' '):
                    pass  # Context lines

        # Mapping line_number to position
        for comment in comments:
            file_path = comment['file_path']
            line_string = comment['line_string']
            issue_comment = comment['comment']

            # Get the latest content of the file from the PR's head commit
            file_contents_response = requests.get(
                f"https://api.github.com/repos/{repo_name}/contents/{file_path}?ref={current_head_sha}",
                headers={'Authorization': f'Bearer {github_token}'}
            )
            if file_contents_response.status_code != 200:
                print(f"Failed to fetch contents of file {file_path}: {file_contents_response.status_code}")
                continue

            file_contents = file_contents_response.json()
            file_text = base64.b64decode(file_contents['content']).decode('utf-8').splitlines()

            # Find the line number based on line_string
            line_number = None
            for idx, line in enumerate(file_text, start=1):
                if line.strip() == line_string.strip():
                    line_number = idx
                    break

            if line_number is None:
                print(f"Line string '{line_string}' not found in file {file_path}.")
                continue

            # Find the corresponding position in diff
            position_in_diff = None
            if file_path in file_hunks:
                for hunk in file_hunks[file_path]:
                    start_line = hunk['start_line']
                    added_lines = hunk['lines']
                    for i, added_line in enumerate(added_lines):
                        if added_line.strip() == line_string.strip():
                            position_in_diff = start_line + i
                            break
                    if position_in_diff:
                        break

            if position_in_diff is None:
                print(f"Could not map line number {line_number} to position in diff for file {file_path}.")
                continue

            # Cek apakah sudah ada komentar pada file dan posisi ini
            if (file_path, position_in_diff) in existing_comments_set:
                print(f"Comment already exists for {file_path} at position {position_in_diff}, skipping.")
                continue

            # Tambahkan ke payload
            comment_payload.append({
                "path": file_path,
                "position": position_in_diff,
                "body": f"**Finding**: {issue_comment}\n(Line: {line_number})"
            })

        if comment_payload:
            pr.create_review(
                event="COMMENT",
                comments=comment_payload
            )
            print(f"Posted {len(comment_payload)} new review comments.")

            # Tambahkan komentar Last Processed SHA
            pr.create_issue_comment(f"@ai-reviewer Last Processed SHA: {current_head_sha}")
        else:
            print("No new comments to post.")

    except Exception as e:
        raise RuntimeError(f"Failed to post comments: {str(e)}")


@retry(max_retries=2, delay=3)
def post_summary(summary: str, footer_text: str, pr):
    """Post the summary advice as an issue comment"""
    try:
        pr.create_issue_comment(
            f"## 📝 {footer_text}\n\n{summary}"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to post summary comment: {str(e)}")


def main():
    """Main execution workflow"""
    try:
        # Configuration
        model_name = os.getenv('INPUT_MODEL_NAME', 'gemini-1.5-pro-latest')
        custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')
        max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '100000'))
        footer_text = os.getenv('INPUT_FOOTER_TEXT', 'AI Code Review Report')

        # Initialize GitHub client
        github_token = os.getenv('GITHUB_TOKEN')
        repo_name = os.getenv('GITHUB_REPOSITORY')
        g = Github(github_token)
        repo = g.get_repo(repo_name)
        pr_number = get_pr_number()
        pr = repo.get_pull(pr_number)

        # Get current head SHA
        current_head_sha = pr.head.sha

        # Cek apakah sudah ada commit baru yang belum diproses
        existing_issue_comments = pr.get_issue_comments()
        last_processed_sha = None
        for comment in existing_issue_comments:
            if comment.body.startswith("@ai-reviewer Last Processed SHA:"):
                last_processed_sha = comment.body.split(":")[1].strip()
                break

        if last_processed_sha == current_head_sha:
            print("No new commits to process. Skipping diff processing to avoid duplication.")
            return

        # Get PR diff
        diff_content = get_pr_diff(pr)
        if len(diff_content) > max_diff_size:
            print(f"⚠️ Diff size ({len(diff_content)} bytes) exceeds limit")
            return

        # Generate review
        review_data = generate_review(diff_content, model_name, custom_instructions)

        # Post summary
        post_summary(review_data['summary_advice'], footer_text, pr)

        print("Debug Review Data:")
        print(review_data)
        print("Debug Review Data End")

        # Post individual comments
        post_comment(review_data['response'], pr, repo_name, github_token, current_head_sha, diff_content)

        print("✅ Review completed successfully")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()
