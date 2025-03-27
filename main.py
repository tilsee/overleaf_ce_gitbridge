import json
import logging
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("github_bridge")


class Config:
    """Configuration manager for GitHub Bridge application."""
    
    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        import os
        load_dotenv()
        
        self.github_token = os.getenv("GITHUB_TOKEN")
        if not self.github_token:
            logger.error("GITHUB_TOKEN not found in environment variables")
        
        # Use Path objects for better path handling
        self.compiles_dir = Path(os.getenv("COMPILES_DIR", "/data/compiles"))
        self.temp_dir_base = Path(os.getenv("TEMP_DIR_BASE", "/tmp/git_operations"))
        self.gitignore_template = Path(os.getenv(
            "GITIGNORE_TEMPLATE", 
            Path(__file__).parent / "gitignore.example"
        ))
        
        # Git configuration
        self.git_user_name = os.getenv("GIT_USER_NAME", "GitBridge")
        self.git_user_email = os.getenv("GIT_USER_EMAIL", "gitbridge@example.com")
        self.gitinfo_filename = os.getenv("GITINFO_FILENAME", ".gitinfo")
        self.commit_message_template = os.getenv("COMMIT_MESSAGE_TEMPLATE", 
                                               "Update from Overleaf ({folder_name})")
        self.check_interval = int(os.getenv("CHECK_INTERVAL", "300"))
        
        # Create temp directory if it doesn't exist
        self.temp_dir_base.mkdir(parents=True, exist_ok=True)


class GitOperations:
    """Handles all Git-related operations."""
    
    def __init__(self, config: Config) -> None:
        self.config = config
    
    def add_token_to_url(self, url: str, token: Optional[str]) -> str:
        """Add GitHub token to repository URL for authentication."""
        if not token or not url.startswith("https://github.com/"):
            return url
        
        return url.replace("https://github.com/", f"https://{token}@github.com/")
    
    def run_git_command(self, cmd: List[str], cwd: Optional[Union[str, Path]] = None, 
                        check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command safely without leaking credentials."""
        try:
            return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            # Sanitize error output to remove token
            if self.config.github_token:
                e.stderr = e.stderr.replace(self.config.github_token, "***TOKEN***")
            logger.error(f"Git command failed: {e.stderr}")
            raise
            
    def has_tracked_files(self, repo_dir: Path) -> bool:
        """Check if the repository has any tracked files."""
        try:
            result = self.run_git_command(["git", "ls-files"], cwd=repo_dir, check=False)
            return bool(result.stdout.strip())
        except Exception:
            logger.exception("Error checking for tracked files")
            return False


class GitHubBridge:
    """Main application class for GitHub Bridge functionality."""
    
    def __init__(self, config: Config) -> None:
        self.config = config
        self.git = GitOperations(config)
        self.running = True
        
        # Set up signal handlers for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)
    
    def _signal_handler(self, sig: int, frame: Any) -> None:
        """Handle termination signals for graceful shutdown."""
        logger.info("Shutdown signal received, exiting gracefully...")
        self.running = False
    
    def process_folders(self) -> None:
        """Process folders in the compiles directory and sync with repositories."""
        if not self.config.compiles_dir.is_dir():
            logger.error(f"Directory {self.config.compiles_dir} does not exist")
            return

        for folder_path in [p for p in self.config.compiles_dir.iterdir() if p.is_dir()]:
            gitinfo_path = folder_path / self.config.gitinfo_filename
            
            if not gitinfo_path.is_file():
                continue
            
            try:
                # Read and parse gitinfo file
                gitinfo = json.loads(gitinfo_path.read_text())
                
                if not (repo_url := gitinfo.get("gitrepo")):
                    logger.warning(f"No gitrepo found in {gitinfo_path}")
                    continue
                
                # Convert URL to authenticated URL using token
                auth_repo_url = self.git.add_token_to_url(repo_url, self.config.github_token)
                
                # Process the repository
                self.sync_with_github(folder_path, auth_repo_url, repo_url)
                
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in {gitinfo_path}")
            except Exception:
                logger.exception(f"Error processing {folder_path}")
    
    def sync_with_github(self, folder_path: Path, auth_repo_url: str, public_repo_url: str) -> None:
        """Clone repository, update with folder contents, commit and push changes."""
        folder_name = folder_path.name
        temp_dir = self.config.temp_dir_base / f"temp_git_{folder_name}"
        
        try:
            # Clean up any existing temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            
            # Clone repository
            logger.info(f"Cloning repository for {folder_name}...")
            self.git.run_git_command(["git", "clone", "--depth=1", auth_repo_url, str(temp_dir)])
            
            # Add gitignore if needed
            gitignore_path = temp_dir / ".gitignore"
            if self.config.gitignore_template.exists():
                logger.info("Adding/updating .gitignore file for TeX artifacts")
                shutil.copy2(self.config.gitignore_template, gitignore_path)
            
            # Files to preserve during cleanup
            preserve_files = {'.git', '.gitignore'}
            
            # Clean repository except preserved files
            logger.info(f"Cleaning repository to match {folder_name} contents...")
            for item in temp_dir.iterdir():
                if item.name not in preserve_files:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
            
            # Copy contents from source folder to repository
            logger.info(f"Copying files from {folder_name} to the repository...")
            for item in folder_path.iterdir():
                if item.name == self.config.gitinfo_filename:
                    continue
                
                destination = temp_dir / item.name
                
                if item.is_dir():
                    shutil.copytree(item, destination)
                else:
                    shutil.copy2(item, destination)
            
            # Stage all changes before checking the status
            self.git.run_git_command(["git", "add", "-A"], temp_dir)
            
            # Check if there are changes to commit
            status = self.git.run_git_command(["git", "status", "--porcelain"], temp_dir).stdout.strip()
            
            if not status:
                logger.info(f"No changes detected for {folder_name}, skipping commit and push")
                return
            
            # Commit and push changes
            try:
                # Configure Git user identity
                self.git.run_git_command(["git", "config", "user.name", self.config.git_user_name], temp_dir)
                self.git.run_git_command(["git", "config", "user.email", self.config.git_user_email], temp_dir)
                
                commit_message = self.config.commit_message_template.format(folder_name=folder_name)
                self.git.run_git_command(["git", "commit", "-m", commit_message], temp_dir)
                
                logger.info("Pushing changes to repository...")
                self.git.run_git_command(["git", "push"], temp_dir)
                logger.info(f"Successfully synced {folder_name} with GitHub repository: {public_repo_url}")
                
            except subprocess.CalledProcessError as e:
                sanitized_stderr = e.stderr
                if self.config.github_token:
                    sanitized_stderr = sanitized_stderr.replace(self.config.github_token, "***TOKEN***")
                
                if any(msg in sanitized_stderr for msg in ["nothing to commit", "no changes added to commit"]):
                    logger.info(f"No changes to commit for {folder_name}")
                else:
                    logger.error(f"Git commit failed: {sanitized_stderr}")
                    raise
                    
        except Exception:
            logger.exception(f"Error syncing {folder_name} with GitHub")
        finally:
            # Clean up temporary directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
    
    def run(self) -> None:
        """Main loop to continuously scan for changes and sync with repositories."""
        logger.info(f"Starting GitHub Bridge (checking every {self.config.check_interval} seconds)")
        
        if not self.config.compiles_dir.is_dir():
            logger.error(f"Compiles directory {self.config.compiles_dir} does not exist. "
                         f"Please check your configuration.")
            sys.exit(1)
        
        try:
            while self.running:
                logger.info("Scanning for projects to sync...")
                self.process_folders()
                logger.info(f"Scan complete. Next check in {self.config.check_interval} seconds")
                
                # Sleep with interruption handling
                self._sleep_with_interruption(self.config.check_interval)
        
        except Exception:
            logger.exception("Unexpected error in main loop")
        
        logger.info("GitHub Bridge stopped")
    
    def _sleep_with_interruption(self, seconds: int) -> None:
        """Sleep with periodic checking for interruption signals."""
        check_interval = 1  # Check every second
        for _ in range(seconds):
            if not self.running:
                break
            time.sleep(check_interval)


if __name__ == "__main__":
    config = Config()
    bridge = GitHubBridge(config)
    bridge.run()
