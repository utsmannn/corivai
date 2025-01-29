#!/usr/bin bash

GITLAB_TOKEN=${GITLAB_CI_TOKEN}
CI_PROJECT_ID=${CI_PROJECT_ID}
API_KEY=${REVIEWER_API_KEY}

python -m src.main-gitlab