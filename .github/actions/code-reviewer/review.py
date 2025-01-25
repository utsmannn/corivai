import os
import requests
from github import Github
import google.generativeai as genai

def anu():








    return ""


def get_pr_diff() -> str:
    """
    Retrieves pull request diff using GitHub API
    Returns:
        Diff content as string
    """
    # Get environment variables
    github_token = os.getenv('GITHUB_TOKEN')
    repo_name = os.getenv('GITHUB_REPOSITORY')
    pr_number = os.getenv('GITHUB_REF').split('/')[-2]

    # Configure API request
    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3.diff'
    }
    url = f'https://api.github.com/repos/{repo_name}/pulls/{pr_number}'

    # Execute request
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to get diff: {response.status_code}")
    return response.text


def generate_review(diff: str, model_name: str, custom_instructions: str) -> str:
    """
    Generates code review using Gemini API
    Args:
        diff: Code diff content
        model_name: Gemini model name
        custom_instructions: Additional review guidelines
    Returns:
        Generated review text
    """
    try:
        # Initialize Gemini model
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        model = genai.GenerativeModel(model_name)

        # Construct prompt
        base_prompt = """Perform comprehensive code review considering:
1. Code quality and readability
2. Potential bugs and edge cases
3. Security vulnerabilities
4. Performance optimizations
5. Adherence to best practices"""

        custom_prompt = ""
        if custom_instructions:
            custom_prompt = f"\n\nAdditional Requirements:\n{custom_instructions}"

        full_prompt = f"""{base_prompt}{custom_prompt}

Format output as markdown with sections:
- **✅ Strengths**
- **⚠️ Concerns**
- **💡 Recommendations**

Focus on actual code changes. Be specific and provide code examples when possible.

Code Diff:
{diff}"""

        # Generate content
        response = model.generate_content(
            full_prompt,
            safety_settings={
                'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
            }
        )
        return response.text

    except Exception as e:
        raise ValueError(f"Generation error: {str(e)}")


def post_comment(review_text: str, model: str):
    """
    Posts review comment to pull request
    Args:
        review_text: Review content to post
    """
    # Initialize GitHub client
    github_token = os.getenv('GITHUB_TOKEN')
    repo_name = os.getenv('GITHUB_REPOSITORY')
    pr_number = os.getenv('GITHUB_REF').split('/')[-2]

    g = Github(github_token)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(int(pr_number))

    footer = f'''
    
    🤖 Review by {model} with Corivai.
    '''

    # Post comment
    pr.create_issue_comment(f"{review_text}\n{footer}")


if __name__ == "__main__":
    try:
        # Get inputs
        model_name = os.getenv('INPUT_MODEL-NAME', 'gemini-1.5-pro-latest')
        custom_instructions = os.getenv('INPUT_CUSTOM-INSTRUCTIONS', '')

        # Validate and get diff
        diff_content = get_pr_diff()
        if len(diff_content) > 100000:  # ~100KB limit
            print("⚠️ Diff size exceeds limit, skipping review")
            exit(0)

        # Generate and post review
        review = generate_review(diff_content, model_name, custom_instructions)
        post_comment(review, model_name)
        print("✅ Review completed successfully")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        exit(1)