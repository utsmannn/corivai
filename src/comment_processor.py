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


    all_comment = pr.get_review_comments()


    if commend_id:
        comment = pr.get_comment(int(commend_id))
        reply_to_id = comment.in_reply_to_id
        parent = pr.get_comment(reply_to_id)

        in_replies_to = [com for com in all_comment if com.in_reply_to_id == reply_to_id]

        print(f"cuaks system --> {parent.diff_hunk}")
        print(f"cuaks assistant ----> {parent.user.login}: {parent.body} | {parent.in_reply_to_id}")
        for com in in_replies_to:
            print(f"cuaks user ----> {com.user.login}: {com.body} | {com.in_reply_to_id}")


def main():
    get_review_comments()


if __name__ == '__main__':
    main()