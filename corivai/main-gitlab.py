import logging
import os
import sys

from corivai.config import CorivaiConfig
from corivai.exceptions import ReviewError
from corivai.pr_reviewer import PRReviewer
from corivai.git_gitlab import GitGitlab


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

        api_key = os.getenv('API_KEY')
        baseUrl = os.getenv('INPUT_OPENAI-URL', 'https://api.openai.com/v1')
        model = os.getenv('INPUT_MODEL-NAME', '')
        gitlab_token = os.getenv('GITLAB_TOKEN')
        max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '500000'))
        custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')
        config = CorivaiConfig(
            api_key=api_key,
            openai_url=baseUrl,
            model_name=model,
            git_token=gitlab_token,
            max_diff_size=max_diff_size,
            custom_instruction=custom_instructions
        )

        # Initialize and run PR reviewer
        reviewer = PRReviewer(git_interface=git_interface, config=config)
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