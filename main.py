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
    headers = {
        'Authorization': f'Bearer {os.getenv("GITHUB_TOKEN")}',
        'Accept': 'application/vnd.github.v3.diff'
    }
    url = f'https://api.github.com/repos/corivai/pulls/53'
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

    # Print structured diff for verification
    print("\nStructured Diff:")
    print(json.dumps(structured_diff, indent=2))

    # Generate review using AI
    # review_response = reviewer.generator.generate(json.dumps(structured_diff))
    #
    # # Print review response
    # print("\nReview Response:")
    # for comment in review_response.comments:
    #     print(f"\nFile: {comment.file_path}")
    #     print(f"Line: {comment.line_string}")
    #     print(f"Comment: {comment.comment}")


if __name__ == "__main__":
    main()