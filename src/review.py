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

def find_line_number(file_path: str, line_str: str) -> int:
    """Cari line number berdasarkan konten line string"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                # Normalisasi whitespace untuk matching lebih akurat
                if line.strip() == line_str.strip():
                    return line_num
        return -1  # Jika tidak ditemukan
    except Exception as e:
        raise RuntimeError(f"Gagal baca file {file_path}: {str(e)}")

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
            system_instruction="you are git diff analyzer for give me review line per line code"
        )

        safe_diff = sanitize_input(diff, 50000)
        instructions = sanitize_input(custom_instructions)

        prompt = f"""**Code Review Task**
Analyze this code diff and generate structured feedback:
{safe_diff}

**Requirements:**
- Berikan line string yang spesifik dari kode
- Contoh response: 
{{
  "response": [
    {{
      "comment": "Potential SQL injection",
      "file_path": "src/db.py",
      "line_string": "query = f\"SELECT * FROM users WHERE id = user_id\""
    }}
  ]
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
            original_line = find_line_number(comment['file_path'], comment['line_string'])
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

        # Get PR diff
        diff_content = get_pr_diff()
        if len(diff_content) > max_diff_size:
            print(f"⚠️ Diff size ({len(diff_content)} bytes) exceeds limit")
            return

        # Generate review
        review_data = generate_review(diff_content, model_name, custom_instructions)

        # Post individual comments


        # Post summary
        g = Github(os.getenv('GITHUB_TOKEN'))
        repo = g.get_repo(os.getenv('GITHUB_REPOSITORY'))
        pr = repo.get_pull(get_pr_number())
        pr.create_issue_comment(
            f"## 📝 {footer_text}\n\n{review_data['summary_advice']}"
        )

        print("asuuu..")
        print(review_data)
        print("asuuu..0")
        post_comment(review_data['response'])

        print("✅ Review completed successfully")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        exit(1)


if __name__ == "__main__":
    main()