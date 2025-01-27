import os
import requests
import logging

from github import Github

from src import ReviewError

# logger = logging.getLogger(__name__)


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
    commend_id = os.environ['COMMENT_ID']

    github = Github(token)
    repo = github.get_repo(repo)

    pr_number = get_pr_number()
    pr = repo.get_pull(pr_number)

    print(f"cuaks comment id -> {commend_id}")
    print(f"cuaks thread id -> {thread_id}")


    for rc in pr.get_review_comments():
        print(f"cuaks acuu --> {rc.pull_request_review_id} | thread: {thread_id}")

    # for com in pr.get_review_comments()

    for com in pr.get_comments():
        print(f"cuaksssss ---> | {com.pull_request_review_id} ---> {thread_id}")

    if thread_id:
        # thread = pr.get_review_comment(int(thread_id))
        comments = pr.get_comments()
        for com in comments:
            if com.pull_request_review_id == int(thread_id):
                print(f"asuu ada nih | {com.user.login}: {com.body}")

    # if thread_id:
    #     comments = pr.get_review_comment(int(thread_id))
    #     logger.info(f"cuaks ---> | {comments.pull_request_review_id} | {thread_id}")

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