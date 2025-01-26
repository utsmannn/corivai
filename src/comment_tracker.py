# src/comment_tracker.py
import os
import requests


def get_comments():
    token = os.environ['GITHUB_TOKEN']
    repo = os.environ['REPO']
    issue_number = os.environ['ISSUE_NUMBER']

    owner, repo_name = repo.split('/')

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    url = f'https://api.github.com/repos/{owner}/{repo_name}/issues/{issue_number}/comments'
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        comments = response.json()
        print('Issue Comment Thread:')
        for i, comment in enumerate(comments, 1):
            print(f"\n--- Comment {i} ---")
            print(f"Author: {comment['user']['login']}")
            print(f"Created: {comment['created_at']}")
            print(f"Content: {comment['body']}")
    else:
        print(f"Error fetching comments: {response.status_code}")


if __name__ == '__main__':
    get_comments()