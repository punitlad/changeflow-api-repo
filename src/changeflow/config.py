from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class MergeMode(str, Enum):
    NATIVE_AUTO_MERGE = "native_auto_merge"  # enable GitHub auto-merge on the PR
    RULESET_BYPASS = "ruleset_bypass"        # app is on the bypass list; merge via REST
    WORKFLOW_GATED = "workflow_gated"        # their workflow merges; we only wait


class ApprovalMode(str, Enum):
    PENDING_DEPLOYMENTS = "pending_deployments"  # needs a *user* token that is a required reviewer
    PROTECTION_RULE = "protection_rule"          # our GitHub App is a custom deployment protection rule


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHANGEFLOW_", env_file=".env")

    github_api_url: str = "https://api.github.com"

    # GitHub App identity (opens PRs, merges, reads runs)
    app_id: int
    app_private_key: str  # PEM contents
    installation_id: int

    # Target repo owned by the external service
    target_owner: str
    target_repo: str
    base_branch: str = "main"
    json_path: str = "teams.json"
    # Key holding the array. Set to "" if the file root is the array itself.
    json_array_key: str = "teams"

    # Pipeline
    pipeline_workflow_file: str = "deploy.yml"  # workflow triggered on push to base_branch
    pipeline_environment: str | None = None     # environment name with required reviewers

    merge_mode: MergeMode = MergeMode.RULESET_BYPASS
    merge_method: str = "squash"  # squash | merge | rebase

    approval_mode: ApprovalMode = ApprovalMode.PENDING_DEPLOYMENTS
    # Only for PENDING_DEPLOYMENTS: a machine *user* PAT that is a required reviewer.
    # GitHub Apps cannot be environment reviewers.
    approver_token: str | None = None

    # Timeouts (seconds)
    merge_timeout: int = 900
    run_discovery_timeout: int = 300
    approval_timeout: int = 1800
    pipeline_timeout: int = 3600
    poll_interval: int = 10
