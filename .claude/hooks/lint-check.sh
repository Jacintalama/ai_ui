#!/bin/bash
input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path')
if [[ "$file_path" == *.ts || "$file_path" == *.js ]]; then
  npm run lint --silent "$file_path" 2>&1 || true
fi