import os
from typing import Dict, List
import requests
import gitlab
from gitlab.v4.objects import MergeRequest
import logging

from src.git_interface import GitInterface
from src.exceptions import ReviewError

logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
logger = logging.getLogger(__name__)


class GitGitlab(GitInterface):
    def __init__(self, token: str, repo_identifier: str):
        self.token = token
        self.project_id = repo_identifier
        self.gitlab_url = os.getenv('CI_SERVER_URL', 'https://gitlab.com')
        self.gl = gitlab.Gitlab(self.gitlab_url, private_token=token)
        self.project = self.gl.projects.get(repo_identifier)

    def get_request_number(self) -> int:
        mr_iid = os.getenv('CI_MERGE_REQUEST_IID')
        if not mr_iid:
            raise ReviewError("CI_MERGE_REQUEST_IID not found")
        try:
            return int(mr_iid)
        except ValueError as e:
            raise ReviewError(f"Invalid merge request IID format: {str(e)}")

    def get_request(self, number: int) -> MergeRequest:
        return self.project.mergerequests.get(number)

    def get_diff(self, request: MergeRequest) -> str:
        headers = {
            'PRIVATE-TOKEN': self.token
        }
        url = f'{self.gitlab_url}/api/v4/projects/{self.project_id}/merge_requests/{request.iid}/changes'
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        changes = response.json().get('changes', [])
        diff_content = []

        for change in changes:
            diff_content.append(f"diff --git a/{change['old_path']} b/{change['new_path']}")
            diff_content.append(change['diff'])

        return '\n'.join(diff_content)

    def get_review_comments(self, request: MergeRequest) -> List[Dict]:
        discussions = request.discussions.list()
        comments = []

        for discussion in discussions:
            for note in discussion.attributes.get('notes', []):
                if note.get('type') == 'DiffNote':
                    comments.append({
                        'path': note.get('position', {}).get('new_path'),
                        'position': note.get('position', {}).get('new_line'),
                        'body': note.get('body'),
                        'diff_hunk': note.get('position', {}).get('new_line')
                    })

        return comments

    def create_review_comment(self, request: MergeRequest, file_path: str, position: int, body: str) -> None:
        logger.info(f"new line -------> {position}")
        request.discussions.create({
            'body': body,
            'position': {
                'base_sha': request.diff_refs['base_sha'],
                'start_sha': request.diff_refs['start_sha'],
                'head_sha': request.diff_refs['head_sha'],
                'position_type': 'text',
                'new_path': file_path,
                'new_line': position
            }
        })

    def create_review(self, request: MergeRequest, comments: List[Dict]) -> None:
        for comment in comments:
            self.create_review_comment(
                request,
                comment['path'],
                comment['position'],
                comment['body']
            )

    def create_issue_comment(self, request: MergeRequest, body: str) -> None:
        request.notes.create({'body': body})

    def get_head_sha(self, request: MergeRequest) -> str:
        return request.sha
