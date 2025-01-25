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
def get_pr_diff() -> dict:
    """Retrieve PR diffs from GitHub API"""
    try:
        pr_number = get_pr_number()
        repo_name = os.getenv('GITHUB_REPOSITORY')
        github_token = os.getenv('GITHUB_TOKEN')

        if not repo_name or not github_token:
            raise ValueError("Environment variables GITHUB_REPOSITORY or GITHUB_TOKEN not found.")

        headers = {
            'Authorization': f'Bearer {github_token}',
            'Accept': 'application/vnd.github.v3.diff'
        }

        # Fetch the overall diff between the target branch and the PR branch
        overall_diff_response = requests.get(
            f'https://api.github.com/repos/{repo_name}/pulls/{pr_number}',
            headers=headers
        )
        overall_diff_response.raise_for_status()
        overall_diff = overall_diff_response.text

        # Fetch the list of commits in the PR
        commits_response = requests.get(
            f'https://api.github.com/repos/{repo_name}/pulls/{pr_number}/commits',
            headers=headers
        )
        commits_response.raise_for_status()
        commits = commits_response.json()

        commit_diffs = []
        if len(commits) >= 2:
            # Only process the last two commits
            last_commit = commits[-1]
            second_last_commit = commits[-2]

            current_sha = last_commit['sha']
            previous_sha = second_last_commit['sha']

            # Fetch the diff for the last commit compared to the second last commit
            commit_diff_response = requests.get(
                f'https://api.github.com/repos/{repo_name}/compare/{previous_sha}...{current_sha}',
                headers={'Authorization': f'Bearer {github_token}', 'Accept': 'application/vnd.github.v3.diff'}
            )
            commit_diff_response.raise_for_status()
            commit_diff = commit_diff_response.text

            commit_diffs.append({
                'commit_sha': current_sha,
                'commit_message': last_commit['commit']['message'].strip(),
                'diff': commit_diff
            })

        return {
            'overall_diff': overall_diff,
            'commit_diffs': commit_diffs
        }

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch PR diffs: {str(e)}")


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
def post_comment(comments: list):
    """Post comments by finding accurate line numbers based on line_string"""
    try:
        pr_number = get_pr_number()
        github_token = os.getenv('GITHUB_TOKEN')
        repo_name = os.getenv('GITHUB_REPOSITORY')

        if not github_token or not repo_name:
            raise ValueError("Environment variables GITHUB_TOKEN or GITHUB_REPOSITORY not found.")

        g = Github(github_token)
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        files = pr.get_files()  # Get list of changed files

        comment_payload = []

        for comment in comments:
            file_path = comment['file_path']
            line_string = comment['line_string']
            issue_comment = comment['comment']

            # Find the file in the PR
            target_file = next((f for f in files if f.filename == file_path), None)

            if not target_file or not target_file.patch:
                print(f"File {file_path} not found in PR or does not have a patch.")
                continue

            # Get the latest content of the file from the PR's head commit
            file_contents_response = requests.get(
                f"https://api.github.com/repos/{repo_name}/contents/{file_path}?ref={pr.head.sha}",
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

            # Add comment with accurate line number
            comment_payload.append({
                "path": file_path,
                "position": line_number,  # Accurate line number
                "body": f"**Finding**: {issue_comment}\n(Line: {line_number})"
            })

        if comment_payload:
            pr.create_review(
                event="COMMENT",
                comments=comment_payload
            )
        else:
            print("No comments to post.")

    except Exception as e:
        raise RuntimeError(f"Failed to post comments: {str(e)}")


@retry(max_retries=2, delay=3)
def post_summary(summary: str, footer_text: str):
    """Post the summary advice as an issue comment"""
    try:
        pr_number = get_pr_number()
        github_token = os.getenv('GITHUB_TOKEN')
        repo_name = os.getenv('GITHUB_REPOSITORY')

        if not github_token or not repo_name:
            raise ValueError("Environment variables GITHUB_TOKEN or GITHUB_REPOSITORY not found.")

        g = Github(github_token)
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

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

        # Get PR diffs
        diffs = get_pr_diff()
        overall_diff = diffs['overall_diff']
        commit_diffs = diffs['commit_diffs']

        if len(overall_diff) > max_diff_size:
            print(f"⚠️ Diff size ({len(overall_diff)} bytes) exceeds limit")
            return

        # Generate review for overall diff
        overall_review = generate_review(overall_diff, model_name, custom_instructions)

        # Post summary for overall review
        post_summary(overall_review['summary_advice'], footer_text)

        print("Debug Overall Review Data:")
        print(overall_review)
        print("Debug Overall Review Data End")

        # Post individual comments for overall diff
        post_comment(overall_review['response'])

        # Generate and post reviews for each of the last two commit diffs
        for commit_diff in commit_diffs:
            print(f"Processing commit: {commit_diff['commit_sha']} - {commit_diff['commit_message']}")
            commit_review = generate_review(commit_diff['diff'], model_name, custom_instructions)

            # Post summary for commit review
            post_summary(commit_review['summary_advice'], footer_text)

            print("Debug Commit Review Data:")
            print(commit_review)
            print("Debug Commit Review Data End")

            # Post individual comments for commit diff
            post_comment(commit_review['response'])

        print("✅ Review completed successfully")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()
