import logging
import os
import sys

from src.exceptions import ReviewError
from src.pr_reviewer import PRReviewer
from src.git_gitlab import GitGitlab


logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
logger = logging.getLogger(__name__)

def main():
    try:
        # Get required environment variables
        gitlab_token = os.getenv('GITLAB_TOKEN')
        project_id = os.getenv('CI_PROJECT_ID')

        if not all([gitlab_token, project_id]):
            raise ReviewError("Missing required environment variables: GITLAB_TOKEN, CI_PROJECT_ID")

        # Initialize GitLab interface
        git_interface = GitGitlab(
            token=gitlab_token,
            repo_identifier=project_id
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