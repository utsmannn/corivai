# Corivai - AI-Powered Code Review Assistant

Corivai is a GitHub Action that provides automated code reviews and interactive discussions using various AI models. It not only reviews your pull requests but also engages in meaningful conversations through comments, offering explanations and clarifications when needed.

## Features

### Automated Code Review
- Code quality assessment and best practices recommendations
- Potential bug detection and security vulnerability identification
- Performance optimization suggestions
- Coding style and consistency checks

### Interactive Comment Responses
- AI-powered responses to questions about its review comments
- Detailed explanations of suggested changes
- Technical discussions through comment threads
- Contextual understanding of the code being discussed

## Setup Instructions

### 1. Required Secrets

Add these secrets to your GitHub repository:
- `REVIEWER_API_KEY`: Your API key for the chosen AI provider
- `GITHUB_TOKEN`: Automatically provided by GitHub Actions

### 2. Workflow Configuration

Create `.github/workflows/code-review.yml` in your repository:

```yaml
name: AI Code Review

on:
  # Triggered when a pull request is opened or updated
  pull_request:
    types: [opened, synchronize]
    
  # Triggered when someone comments on a review
  pull_request_review_comment:
    types: [created]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      contents: write
      
    steps:
      - uses: actions/checkout@v3
      
      - name: AI Code Review
        uses: utsmannn/corivai@v1
        with:
          reviewer-api-key: ${{ secrets.REVIEWER_API_KEY }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
          model-name: 'your-model-name'
          open-ai-url: 'your-endpoint-url'
          max-diff-size: '100000'
          custom-instructions: |
            Your custom review guidelines here
```

## Configuration Parameters

| Parameter | Required | Description | Default | Example Values |
|-----------|----------|-------------|---------|----------------|
| reviewer-api-key | Yes | Authentication key for AI service | - | Gemini API key, 'ollama' |
| github-token | Yes | GitHub token for API access | - | ${{ secrets.GITHUB_TOKEN }} |
| model-name | Yes | AI model identifier | - | 'gemini-pro', 'codellama' |
| open-ai-url | Yes | AI service endpoint URL | - | See provider-specific configs below |
| max-diff-size | No | Maximum diff size in bytes | 100000 | '500000' |
| custom-instructions | No | Additional review guidelines | - | Markdown formatted instructions |

## Provider-Specific Configurations

### Google Gemini API

```yaml
- name: AI Code Review
  uses: utsmannn/corivai@v1
  with:
    reviewer-api-key: ${{ secrets.GEMINI_API_KEY }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
    model-name: 'gemini-pro'
    open-ai-url: 'https://generativelanguage.googleapis.com/v1beta/openai/'
```

### Ollama (Self-hosted or Cloud)

```yaml
- name: AI Code Review
  uses: utsmannn/corivai@v1
  with:
    reviewer-api-key: 'ollama'
    github-token: ${{ secrets.GITHUB_TOKEN }}
    model-name: 'codellama'  # or other models like 'llama2', 'mixtral'
    open-ai-url: 'http://your-ollama-endpoint/v1'
```

## Workflow Details

### Pull Request Review Process

1. When a pull request is opened or updated:
   - The action retrieves the diff content
   - Changes are processed in manageable chunks
   - Each chunk is analyzed by the AI model
   - Review comments are posted on specific lines
   - A completion comment is added with the processed SHA

2. Review comment format:
   ```
   **Finding**: [AI's review comment]
   ```

### Comment Response System

1. When a user replies to a review comment:
   - The action captures the conversation context
   - Processes the entire comment thread
   - Generates a contextually aware response
   - Posts the response as a reply

2. Comment thread handling:
   - Maintains conversation context
   - References the original code snippet
   - Considers all previous replies in the thread
   - Provides detailed technical explanations

## Advanced Usage

### Custom Review Guidelines

```yaml
custom-instructions: |
  ## Review Priority
  1. Security vulnerabilities
  2. Performance issues
  3. Code maintainability
  4. Documentation quality
  
  ## Specific Checks
  - SQL injection vulnerabilities
  - Resource leaks
  - Error handling completeness
  - Test coverage adequacy
```

### Large Repository Configuration

```yaml
- name: AI Code Review
  uses: utsmannn/corivai@v1
  with:
    reviewer-api-key: ${{ secrets.REVIEWER_API_KEY }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
    model-name: 'gemini-pro'
    open-ai-url: 'https://generativelanguage.googleapis.com/v1'
    max-diff-size: '500000'  # Increased for larger diffs
    custom-instructions: |
      Focus on critical issues only
      Skip minor style suggestions
```

## Tested Configurations

### Gemini API Setup
```yaml
model-name: 'gemini-pro'
open-ai-url: 'https://generativelanguage.googleapis.com/v1'
```
Tested features:
- Full code review functionality
- Interactive comment responses
- Context-aware discussions
- Code explanation capabilities

### Ollama Setup
```yaml
model-name: 'codellama'
open-ai-url: 'http://localhost:11434/v1'  # or your hosted endpoint
```
Tested features:
- Complete code analysis
- Technical discussion support
- Performance optimization suggestions
- Security vulnerability detection

## Troubleshooting

### Common Issues

1. Authentication Failures
   - Verify API key validity and permissions
   - Check secret configuration in repository settings
   - Ensure endpoint URL is correctly formatted

2. Review Timeout Issues
   - Reduce max-diff-size parameter
   - Split large pull requests into smaller ones
   - Check AI provider's timeout limits

3. Comment Response Problems
   - Verify GitHub token permissions
   - Check comment thread depth limits
   - Ensure bot has write access to pull requests

### Debug Mode

Add environment variable `ACTIONS_STEP_DEBUG=true` in repository settings for detailed logging.

## Best Practices

1. Pull Request Size
   - Keep changes focused and minimal
   - Split large changes into multiple PRs
   - Target less than 50% of max-diff-size

2. Comment Interactions
   - Ask specific questions in replies
   - Reference relevant code sections
   - Keep thread depth reasonable

3. Custom Instructions
   - Be specific about priorities
   - Include project-specific guidelines
   - Update based on team feedback

## Contributing

We welcome contributions to improve Corivai:

1. Fork the repository
2. Create a feature branch
3. Submit a pull request with detailed description
4. Ensure tests pass and documentation is updated

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and feature requests, please use the GitHub Issues section of the repository.