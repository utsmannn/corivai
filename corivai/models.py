from dataclasses import dataclass
from typing import List

@dataclass
class ReviewComment:
    comment: str
    file_path: str
    line_string: str

@dataclass
class ReviewResponse:
    comments: List[ReviewComment]