import os
import requests


def get_review_comments():
    token = os.environ['GITHUB_TOKEN']
    repo = os.environ['REPO']
    pr_number = os.environ['PR_NUMBER']
    thread_id = os.environ['REVIEW_THREAD_ID']

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    # Get all review comments for the PR
    api_url = f'https://api.github.com/repos/{repo}/pulls/{pr_number}/comments'
    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        all_comments = response.json()
        # Filter comments by thread ID to get the conversation
        thread_comments = [
            comment for comment in all_comments
            if comment['pull_request_review_thread_id'] == int(thread_id)
        ]

        # Sort comments by creation time
        thread_comments.sort(key=lambda x: x['created_at'])

        # Extract the conversation
        conversation = []
        for comment in thread_comments:
            conversation.append({
                'user': comment['user']['login'],
                'body': comment['body'],
                'created_at': comment['created_at']
            })

        return conversation

    return None


def main():
    conversation = get_review_comments()
    if conversation:
        # Process the conversation as needed
        for comment in conversation:
            print(f"{comment['user']} said: {comment['body']}")


if __name__ == '__main__':
    main()