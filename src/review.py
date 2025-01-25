import os
import sys

import git
import requests
import json
import time
import html

from git import Repo
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
    pr_num = os.getenv('GITHUB_REF').split('/')[-2]
    return int(pr_num)


def sanitize_input(text: str, max_length=2000) -> str:
    """Sanitize and truncate user input"""
    return html.escape(text[:max_length]) if text else ""


def get_pr_diff(repo_path: str, pr_branch: str, target_branch: str) -> dict:
    """
    Retrieve PR diffs:
    1. Overall diff between target branch and PR branch.
    2. Diff of each new commit with its parent.

    Returns a dictionary with 'overall_diff' and 'commit_diffs'.
    """
    try:
        repo = Repo(repo_path)
        if repo.bare:
            raise ValueError("Repository is bare.")

        # Fetch the latest changes
        origin = repo.remotes.origin
        origin.fetch()

        # Checkout target and PR branches
        repo.git.checkout(target_branch)
        repo.git.pull(origin, target_branch)

        repo.git.checkout(pr_branch)
        repo.git.pull(origin, pr_branch)

        # 1. Overall diff between target_branch and pr_branch
        overall_diff = repo.git.diff(target_branch, pr_branch)

        # 2. Get list of commits on PR branch that are not on target_branch
        commits = list(repo.iter_commits(f'{target_branch}..{pr_branch}'))
        commits = commits[::-1]  # Dari yang paling lama ke terbaru

        commit_diffs = []
        for commit in commits:
            if commit.parents:
                parent = commit.parents[0]
                diff = repo.git.diff(parent.hexsha, commit.hexsha)
            else:
                # Jika commit pertama tanpa parent
                diff = repo.git.diff(commit.hexsha)
            commit_diffs.append({
                'commit_sha': commit.hexsha,
                'commit_message': commit.message.strip(),
                'diff': diff
            })

        return {
            'overall_diff': overall_diff,
            'commit_diffs': commit_diffs
        }

    except git.exc.GitError as e:
        raise RuntimeError(f"Git operation failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Failed to retrieve PR diff: {str(e)}")


@retry(max_retries=3, delay=2)
def generate_review(diff: str, model_name: str, custom_instructions: str) -> dict:
    print("diff:")
    print(diff)
    print("diff===")
    """Generate structured code review using Gemini"""
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
                            required=["comment", "file_path"],
                            properties={
                                "comment": content.Schema(
                                    type=content.Type.STRING,
                                ),
                                "file_path": content.Schema(
                                    type=content.Type.STRING,
                                ),
                                "line": content.Schema(
                                    type=content.Type.NUMBER,
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
            system_instruction="you are git diff analyzer for give me review line per line code"
        )

        safe_diff = sanitize_input(diff, 50000)
        instructions = sanitize_input(custom_instructions)

        prompt = f"""**Code Review Task**
Analyze this code diff and generate structured feedback:
{safe_diff}

**Requirements:**
- One specific issue per comment
- Include exact file path and line number
- Prioritize security issues first
- Follow these instructions: {instructions}

**Output Format:**
{{
  "response": [
    {{
      "comment": "Issue description",
      "file_path": "src/file.py",
      "line": 10
    }}
  ],
  "summary_advice": "Overall recommendations"
}}"""

        response = model.generate_content(prompt)
        raw_json = response.text.strip().replace('```json', '').replace('```', '')

        # Validate JSON structure
        result = json.loads(response.text)
        print("result:")
        print(result)
        print("result====")
        # if not all(key in result for key in ['response', 'summary_advice']):
        #     raise ValueError("Invalid response structure")
        #
        # for comment in result['response']:
        #     if not all(k in comment for k in ['comment', 'file_path']):
        #         raise ValueError("Invalid comment format")
        #     comment['line'] = comment.get('line', 0)

        return result

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Review generation failed: {str(e)}")


@retry(max_retries=2, delay=3)
def post_comment(comments: list):
    """Post comments dengan offset +4 dan pengecekan batas"""
    try:
        pr_number = get_pr_number()
        github_token = os.getenv('GITHUB_TOKEN')
        repo_name = os.getenv('GITHUB_REPOSITORY')

        g = Github(github_token)
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        files = pr.get_files()  # Dapatkan list file yang diubah

        comment_payload = []

        for comment in comments:
            # Adjust line number dengan offset +4
            original_line = comment['line']
            adjusted_line = original_line + 3  # Offset disesuaikan dengan pola diff

            # Dapatkan diff untuk file yang bersangkutan
            target_file = next((f for f in files if f.filename == comment['file_path']), None)

            if not target_file or not target_file.patch:
                print(f"File {comment['file_path']} tidak ditemukan dalam PR")
                continue

            # Hitung jumlah lines dalam diff
            diff_lines = target_file.patch.split('\n')
            max_position = len(diff_lines)

            # Pastikan adjusted_line tidak melebihi batas diff
            safe_position = min(adjusted_line, max_position)

            # Jika line asli 0, jangan gunakan offset
            final_position = safe_position if original_line > 0 else original_line

            comment_payload.append({
                "path": comment['file_path'],
                "position": final_position,
                "body": f"**Finding**: {comment['comment']}\n(Original line: {original_line})"
            })

        pr.create_review(
            event="COMMENT",
            comments=comment_payload
        )

    except Exception as e:
        raise RuntimeError(f"Failed to post comments: {str(e)}")


def main():
    """Main execution workflow"""
    try:
        # Configuration
        model_name = os.getenv('INPUT_MODEL_NAME', 'gemini-1.5-pro-latest')
        custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')
        max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '100000'))
        footer_text = os.getenv('INPUT_FOOTER_TEXT', 'AI Code Review Report')
        repo_path = os.getenv('GITHUB_WORKSPACE', '.')  # Atur path repositori lokal

        # Cabang PR dan target
        pr_branch = os.getenv('GITHUB_HEAD_REF')  # Biasanya di-set oleh GitHub Actions
        target_branch = os.getenv('GITHUB_BASE_REF', 'main')  # Default ke 'main' jika tidak di-set

        if not pr_branch:
            print("Error: GITHUB_HEAD_REF tidak ditemukan.")
            sys.exit(1)

        # Get PR diffs
        diffs = get_pr_diff(repo_path, pr_branch, target_branch)
        overall_diff = diffs['overall_diff']
        commit_diffs = diffs['commit_diffs']

        if len(overall_diff) > max_diff_size:
            print(f"⚠️ Diff size ({len(overall_diff)} bytes) exceeds limit")
            return

        # Generate review untuk overall diff
        review_data = generate_review(overall_diff, model_name, custom_instructions)

        # Post summary
        g = Github(os.getenv('GITHUB_TOKEN'))
        repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
        pr = repo.get_pull(get_pr_number())
        pr.create_issue_comment(
            f"## 📝 {footer_text}\n\n{review_data['summary_advice']}"
        )

        # Post individual comments dari overall diff
        post_comment(review_data['response'])

        # Jika ingin menambahkan review per commit, Anda bisa iterasi melalui commit_diffs
        for commit_diff in commit_diffs:
            # Misalnya, Anda bisa memanggil generate_review lagi untuk setiap commit_diff['diff']
            # dan memposting komentar terpisah
            pass  # Implementasikan sesuai kebutuhan

        print("✅ Review completed successfully")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()