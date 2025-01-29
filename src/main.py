import logging
import os
import sys

from src.exceptions import ReviewError
from src.pr_reviewer import PRReviewer
from src.git_github import GitGithub

logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
logger = logging.getLogger(__name__)

def main():
    try:

        # Get required environment variables
        github_token = os.getenv('GITHUB_TOKEN')
        repo_name = os.getenv('GITHUB_REPOSITORY')

        if not all([github_token, repo_name]):
            raise ReviewError("Missing required environment variables: GITHUB_TOKEN, GITHUB_REPOSITORY")

        # Initialize GitHub interface
        git_interface = GitGithub(
            token=github_token,
            repo_identifier=repo_name
        )

        # Initialize and run PR reviewer
        reviewer = PRReviewer(git_interface=git_interface)
        reviewer.process_request()

        logger.info("Review process completed successfully")
        return 0

    except ReviewError as e:
        logger.error(f"Review Error: {str(e)}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())