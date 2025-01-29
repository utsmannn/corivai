import json
import os
from typing import List, Dict

from openai import OpenAI

from src.git_github import GitGithub


class CommentProcessor:
    def __init__(self):
        self.token = os.environ['GITHUB_TOKEN']
        self.repo = os.environ['REPO']
        self.comment_id = os.environ.get('COMMENT_ID')
        self.user_login = os.environ.get('USER_LOGIN')

        # OpenAI configuration
        self.base_url = os.getenv('INPUT_OPENAI-URL', 'https://api.openai.com/v1')
        self.api_key = os.getenv('API_KEY')
        self.model_name = os.getenv('INPUT_MODEL-NAME', '')

        # Initialize OpenAI client
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

        # Initialize GitGithub
        self.git_github = GitGithub(token=self.token, repo_identifier=self.repo)

    def generate_ai_response(self, messages: List[Dict]) -> str:
        """Generate AI response using OpenAI."""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=0.2,
                top_p=0.95
            )
            return response.choices[0].message.content
        except Exception as e:
            raise Exception(f"Error processing AI response: {str(e)}")

    def process_review_comments(self):
        """Process review comments and generate AI responses."""
        # Skip if the comment is from github-actions bot
        if self.user_login == 'github-actions[bot]':
            return

        # Get PR number and pull request
        pr_number = self.git_github.get_request_number()
        pr = self.git_github.get_request(pr_number)

        # Get all review comments
        all_comments = self.git_github.get_review_comments(pr)

        if self.comment_id:
            # Get the specific comment and its parent
            comment = pr.get_comment(int(self.comment_id))
            if comment.in_reply_to_id:
                parent = pr.get_comment(comment.in_reply_to_id)

                if parent.diff_hunk:
                    # Get all replies to the parent comment
                    in_replies_to = [
                        com for com in all_comments
                        if com.get('in_reply_to_id') == comment.in_reply_to_id
                    ]

                    # Prepare messages for AI
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

                    # Add all replies to the conversation
                    for reply in in_replies_to:
                        messages.append({
                            "role": "user",
                            "content": reply['body']
                        })

                    # Generate AI response
                    response = self.generate_ai_response(messages)

                    # Create a review comment with the AI response
                    self.git_github.create_review_comment(
                        request=pr,
                        file_path=parent.path,
                        position=parent.position,
                        body=response
                    )

def main():
    reviewer = CommentProcessor()
    reviewer.process_review_comments()


if __name__ == '__main__':
    main()