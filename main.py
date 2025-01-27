import os
import json

import requests
from src import PRReviewer


def setup_test_environment():
    """Set up required environment variables for testing."""
    os.environ['GITHUB_TOKEN'] = os.getenv("GITHUB_TOKEN")
    os.environ['GITHUB_REPOSITORY'] = 'utsmannn/corivai'
    os.environ['GITHUB_REF'] = 'refs/pull/53/merge'
    os.environ['INPUT_MODEL-NAME'] = 'qwen2.5-coder'
    os.environ['INPUT_MAX_DIFF_SIZE'] = '500000'
    os.environ['INPUT_OPEN-AI-URL'] = 'https://o.codeutsman.com/v1'
    os.environ['API_KEY'] = 'ollama'

def read_test_diff():
    """Read diff from a specific PR."""
    token = os.getenv('GITHUB_TOKEN')
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable is required")

    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3.diff'
    }

    # Example: for https://github.com/coriva/coriva-action/pull/53
    # repo would be "coriva/coriva-action"
    repo = "utsmannn/corivai"  # Replace with your repository
    pr_number = 53

    url = f'https://api.github.com/repos/{repo}/pulls/{pr_number}'

    print(f"Requesting URL: {url}")  # Debug line to verify URL
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    return response.text

def main():
    # Set up test environment
    setup_test_environment()

    # Initialize PR reviewer
    reviewer = PRReviewer()

    # Read test diff
    diff_content = read_test_diff()

    print("\nDiff content:")
    print(diff_content)

    # Create structured diff
    structured_diff = reviewer.create_structured_diff(diff_content)

    # logger.info("Starting chunked review generation")
    review_responses = reviewer.process_chunks(structured_diff)

    # Merge all responses
    merged_response = reviewer.merge_review_responses(review_responses)

    # Convert to GitHub comments
    github_comments = reviewer.apply_review_comments(merged_response, structured_diff)

    # Print structured diff for verification
    print("\nGithub comment:")
    print(github_comments)

    # Generate review using AI
    # review_response = reviewer.generator.generate(json.dumps(structured_diff))

    # Print review response
    # print("\nReview Response:")
    # print(review_response)
    # for comment in review_response.comments:
    #     print(f"\nFile: {comment.file_path}")
    #     print(f"Line: {comment.line_string}")
    #     print(f"Comment: {comment.comment}")


if __name__ == "__main__":
    main()