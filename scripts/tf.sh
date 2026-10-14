#!/bin/bash
# Runs terraform in infra/ with temporary credentials from `aws login`.
# (Exports short-lived keys into this process only; nothing is written to disk.)
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-llm-gateway}"
eval "$(aws configure export-credentials --profile "$AWS_PROFILE" --format env)"
unset AWS_PROFILE
cd "$(dirname "$0")/../infra"
exec terraform "$@"
