from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class GitInterface(ABC):
    @abstractmethod
    def __init__(self, token: str, repo_identifier: str):
        """Initialize git interface with token and repository identifier"""
        pass

    @abstractmethod
    def get_request_number(self) -> int:
        """Get pull/merge request number from environment"""
        pass

    @abstractmethod
    def get_request(self, number: int):
        """Get pull/merge request object"""
        pass

    @abstractmethod
    def get_diff(self, request) -> str:
        """Get diff content from pull/merge request"""
        pass

    @abstractmethod
    def get_review_comments(self, request) -> List[Dict]:
        """Get existing review comments"""
        pass

    @abstractmethod
    def create_review_comment(self, request, file_path: str, position: int, body: str) -> None:
        """Create a new review comment"""
        pass

    @abstractmethod
    def create_review(self, request, comments: List[Dict]) -> None:
        """Create a batch of review comments"""
        pass

    @abstractmethod
    def create_issue_comment(self, request, body: str) -> None:
        """Create a general comment on the request"""
        pass

    @abstractmethod
    def get_head_sha(self, request) -> str:
        """Get the current HEAD SHA of the request"""
        pass