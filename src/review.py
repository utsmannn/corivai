import os
import requests
import json
import time
import html
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


@retry(max_retries=3, delay=2)
def get_pr_diff() -> str:
    """Retrieve PR diff from GitHub API"""
    try:
        pr_number = get_pr_number()
        repo_name = os.getenv('GITHUB_REPOSITORY')
        github_token = os.getenv('GITHUB_TOKEN')

        headers = {
            'Authorization': f'Bearer {github_token}',
            'Accept': 'application/vnd.github.v3.diff'
        }

        response = requests.get(
            f'https://api.github.com/repos/{repo_name}/pulls/{pr_number}',
            headers=headers
        )
        response.raise_for_status()

        return response.text

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch PR diff: {str(e)}")


@retry(max_retries=3, delay=2)
def generate_review(diff: str, model_name: str, custom_instructions: str) -> dict:
    """Generate structured code review using Gemini"""
    try:
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

        generation_config = genai.GenerationConfig(
            temperature=1,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            response_mime_type="application/json",
            response_schema=content.Schema(
                type=content.Type.OBJECT,
                properties={
                    "response": content.Schema(
                        type=content.Type.ARRAY,
                        items=content.Schema(
                            type=content.Type.OBJECT,
                            required=["comment", "file_path"],
                            properties={
                                "comment": content.Schema(type=content.Type.STRING),
                                "file_path": content.Schema(type=content.Type.STRING),
                                "line": content.Schema(type=content.Type.NUMBER)
                            }
                        )
                    ),
                    "summary_advice": content.Schema(type=content.Type.STRING)
                },
                required=["response", "summary_advice"]
            )
        )

        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=generation_config
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
        result = json.loads(raw_json)
        if not all(key in result for key in ['response', 'summary_advice']):
            raise ValueError("Invalid response structure")

        for comment in result['response']:
            if not all(k in comment for k in ['comment', 'file_path']):
                raise ValueError("Invalid comment format")
            comment['line'] = comment.get('line', 0)

        return result

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Review generation failed: {str(e)}")


@retry(max_retries=2, delay=3)
def post_comment(comment: dict):
    """Post comment to GitHub with line reference"""
    try:
        pr_number = get_pr_number()
        github_token = os.getenv('GITHUB_TOKEN')
        repo_name = os.getenv('GITHUB_REPOSITORY')

        g = Github(github_token)
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        pr.create_issue_comment(
            body=f"**Code Review Finding**\n\n{comment['comment']}",
            commit_id=pr.head.sha,
            path=comment['file_path'],
            line=comment['line'] or None
        )

    except Exception as e:
        raise RuntimeError(f"Failed to post comment: {str(e)}")


def main():
    """Main execution workflow"""
    try:
        # Configuration
        model_name = os.getenv('INPUT_MODEL_NAME', 'gemini-1.5-pro-latest')
        custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')
        max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '100000'))
        footer_text = os.getenv('INPUT_FOOTER_TEXT', 'AI Code Review Report')

        # Get PR diff
        diff_content = get_pr_diff()
        if len(diff_content) > max_diff_size:
            print(f"⚠️ Diff size ({len(diff_content)} bytes) exceeds limit")
            return

        # Generate review
        review_data = generate_review(diff_content, model_name, custom_instructions)

        # Post individual comments
        for comment in review_data['response']:
            post_comment(comment)
            time.sleep(1)  # Basic rate limiting

        # Post summary
        g = Github(os.getenv('GITHUB_TOKEN'))
        repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
        pr = repo.get_pull(get_pr_number())
        pr.create_issue_comment(
            f"## 📝 {footer_text}\n\n{review_data['summary_advice']}"
        )

        print("✅ Review completed successfully")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()