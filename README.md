# GitBridge

GitBridge is a tool that synchronizes Overleaf/ShareLaTeX compiled projects with GitHub repositories.

## Features

- Automatically detects Overleaf projects linked to GitHub repositories
- Commits and pushes changes from Overleaf to GitHub
- Handles authentication securely
- Adds standard LaTeX .gitignore file to repositories to remove unneeded temporary compile artifacts
- Runs as a watchtower service, continuously checking for changes

## Setup

### Prerequisites

- Docker and Docker Compose
- GitHub personal access token with appropriate permissions
- Access to Overleaf/ShareLaTeX compiles directory

### Configuration

1. Copy the `.env.example` file to `.env` and configure:

```bash
# GitHub authentication token
GITHUB_TOKEN=your_github_token_here

# Path to Overleaf compiles directory (on host)
COMPILES_DIR=/path/to/overleaf/compiles

# Git user configuration
GIT_USER_NAME=GitBridge
GIT_USER_EMAIL=gitbridge@example.com

# Commit message template
COMMIT_MESSAGE_TEMPLATE=Update from Overleaf ({folder_name})

# Check interval in seconds (how often to scan for changes)
CHECK_INTERVAL=300
```

### Running with Docker Compose

```bash
docker-compose up -d
```

## Using with Overleaf

To link an Overleaf project with an existing GitHub repository:

1. Create a `.gitinfo` file in your project with the following content:
```json
{
  "gitrepo": "https://github.com/username/repository"
}
```
2. The next time GitBridge runs when the overleaf project was compiled recently, it will detect this file and push the changes of the project to the specified repository. (pulling changes from the repository to the overleaf project is not supported)

## License

[ GPL-3.0 license](LICENSE)
