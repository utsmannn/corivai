import sys
from pathlib import Path
file = Path(__file__).resolve()
parent, root = file.parent, file.parents[1]
sys.path.append(str(root))

try:
    sys.path.remove(str(parent))
except ValueError: # Already removed
    pass

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