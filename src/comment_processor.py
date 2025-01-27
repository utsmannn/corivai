import os
import requests
import logging

from github import Github

from src import ReviewError

logger = logging.getLogger(__name__)


def get_pr_number() -> int:
    pr_ref = os.getenv('GITHUB_REF')
    if not pr_ref:
        raise ReviewError("GITHUB_REF not found")
    try:
        return int(pr_ref.split('/')[-2])
    except (IndexError, ValueError) as e:
        raise ReviewError(f"Invalid PR reference format: {str(e)}")


def get_review_comments():
    token = os.environ['GITHUB_TOKEN']
    repo = os.environ['REPO']
    thread_id = os.environ['REVIEW_THREAD_ID']

    github = Github(token)
    repo = github.get_repo(repo)

    pr_number = get_pr_number()
    pr = repo.get_pull(pr_number)


    for com in pr.get_comments():
        print(f"cuaksssss ---> | {com.pull_request_review_id} ---> {thread_id}")

    comments = pr.get_comment(int(thread_id))
    # reviews.pull_request_review_id

    print(f"cuaks ---> | {comments.pull_request_review_id} | {thread_id}")

    # headers = {
    #     'Authorization': f'token {token}',
    #     'Accept': 'application/vnd.github.v3+json'
    # }
    #
    # # Get all review comments for the PR
    # api_url = f'https://api.github.com/repos/{repo}/pulls/{pr_number}/comments'
    # response = requests.get(api_url, headers=headers)
    #
    # if response.status_code == 200:
    #     all_comments = response.json()
    #     # Filter comments by thread ID to get the conversation
    #     thread_comments = [
    #         comment for comment in all_comments
    #         if comment['pull_request_review_thread_id'] == int(thread_id)
    #     ]
    #
    #     # Sort comments by creation time
    #     thread_comments.sort(key=lambda x: x['created_at'])
    #
    #     # Extract the conversation
    #     conversation = []
    #     for comment in thread_comments:
    #         conversation.append({
    #             'user': comment['user']['login'],
    #             'body': comment['body'],
    #             'created_at': comment['created_at']
    #         })
    #
    #     return conversation
    #
    # return None


def main():
    get_review_comments()


if __name__ == '__main__':
    main()