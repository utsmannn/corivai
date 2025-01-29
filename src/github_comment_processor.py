import json
import os

from github import Github

from src import ReviewError
from openai import OpenAI, BaseModel


baseUrl = os.getenv('INPUT_OPENAI-URL', 'https://api.openai.com/v1')
apiKey = os.getenv('API_KEY')
client = OpenAI(base_url=baseUrl, api_key=apiKey)
model_name = os.getenv('INPUT_MODEL-NAME', '')


def get_pr_number() -> int:
    pr_ref = os.getenv('GITHUB_REF')
    if not pr_ref:
        raise ReviewError("GITHUB_REF not found")
    try:
        return int(pr_ref.split('/')[-2])
    except (IndexError, ValueError) as e:
        raise ReviewError(f"Invalid PR reference format: {str(e)}")


def generate_ai_response(messages):
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.2,
            top_p=0.95
        )

        return response.choices[0].message.content
    except Exception as e:
        raise Exception(f"Error processing AI response: {str(e)}")



def get_review_comments():
    token = os.environ['GITHUB_TOKEN']
    repo = os.environ['REPO']
    commend_id = os.environ['COMMENT_ID']
    user_login = os.environ['USER_LOGIN']


    if user_login == 'github-actions[bot]':
        return

    github = Github(token)
    repo = github.get_repo(repo)

    pr_number = get_pr_number()
    pr = repo.get_pull(pr_number)

    all_comment = pr.get_review_comments()

    if commend_id:
        comment = pr.get_comment(int(commend_id))
        reply_to_id = comment.in_reply_to_id
        parent = pr.get_comment(reply_to_id)

        if parent.diff_hunk:
            in_replies_to = [com for com in all_comment if com.in_reply_to_id == reply_to_id]

            messages = [
                {
                    "role": "system",
                    "content": json.dumps(parent.diff_hunk)
                },
                {
                    "role": "assistant",
                    "content": parent.body
                }
            ]

            for reply in in_replies_to:
                messages.append({
                    "role": "user",
                    "content": reply.body
                })

            response = generate_ai_response(messages)

            pr.create_review_comment_reply(
                comment_id=reply_to_id,
                body=response
            )


def main():
    get_review_comments()


if __name__ == '__main__':
    main()