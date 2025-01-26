import logging
from .pr_reviewer import PRReviewer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    try:
        reviewer = PRReviewer()
        reviewer.process_pr()
    except Exception as e:
        logger.error(f"Failed to complete review: {str(e)}")
        exit(1)

if __name__ == "__main__":
    main()