import logging
import os
import sys

from src.config import CorivaiConfig
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
        api_key = os.getenv('API_KEY')
        baseUrl = os.getenv('INPUT_OPENAI-URL', 'https://api.openai.com/v1')
        model = os.getenv('INPUT_MODEL-NAME', '')
        github_token = os.getenv('GITHUB_TOKEN')
        max_diff_size = int(os.getenv('INPUT_MAX_DIFF_SIZE', '500000'))
        custom_instructions = os.getenv('INPUT_CUSTOM_INSTRUCTIONS', '')


        config = CorivaiConfig(
            api_key=api_key,
            openai_url=baseUrl,
            model_name=model,
            git_token=github_token,
            max_diff_size=max_diff_size,
            custom_instruction=custom_instructions
        )


        repo_name = os.getenv('GITHUB_REPOSITORY')

        if not all([github_token, repo_name]):
            raise ReviewError("Missing required environment variables: GITHUB_TOKEN, GITHUB_REPOSITORY")

        # Initialize GitHub interface
        git_interface = GitGithub(
            token=github_token,
            repo_identifier=repo_name
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