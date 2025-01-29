import os
from typing import Dict, List
import requests
from github import Github
from github.PullRequest import PullRequest

from src.git_interface import GitInterface
from src.exceptions import ReviewError

class GitGithub(GitInterface):
    def __init__(self, token: str, repo_identifier: str):
        self.token = token
        self.repo_identifier = repo_identifier
        self.github = Github(token)
        self.repo = self.github.get_repo(repo_identifier)

    def get_request_number(self) -> int:
        pr_ref = os.getenv('GITHUB_REF')
        if not pr_ref:
            raise ReviewError("GITHUB_REF not found")
        try:
            return int(pr_ref.split('/')[-2])
        except (IndexError, ValueError) as e:
            raise ReviewError(f"Invalid PR reference format: {str(e)}")

    def get_request(self, number: int) -> PullRequest:
        return self.repo.get_pull(number)

    def get_diff(self, request: PullRequest) -> str:
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github.v3.diff'
        }
        url = f'https://api.github.com/repos/{self.repo_identifier}/pulls/{request.number}'
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text

    def get_review_comments(self, request: PullRequest) -> List[Dict]:
        comments = request.get_review_comments()
        return [{
            'path': comment.path,
            'position': comment.position,
            'body': comment.body,
            'diff_hunk': comment.diff_hunk
        } for comment in comments]

    def create_review_comment(self, request: PullRequest, file_path: str, position: int, body: str) -> None:
        return None

    def create_review(self, request: PullRequest, comments: List[Dict]) -> None:
        request.create_review(
            event="COMMENT",
            comments=comments
        )

    def create_issue_comment(self, request: PullRequest, body: str) -> None:
        request.create_issue_comment(body)

    def get_head_sha(self, request: PullRequest) -> str:
        return request.head.sha