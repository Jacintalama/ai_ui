#!/bin/bash

# Enhanced TypeScript development hook
# Handles compilation checks, formatting, and test auto-run

input=$(cat)
tool_name=$(echo "$input" | jq -r '.tool_name')
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

# Only process TypeScript/JavaScript files
if [[ ! "$file_path" =~ \.(ts|tsx|js|jsx|mjs)$ ]]; then
  exit 0
fi

# Skip node_modules and build directories
if [[ "$file_path" == *"/node_modules/"* ]] || [[ "$file_path" == *"/dist/"* ]] || [[ "$file_path" == *"/build/"* ]]; then
  exit 0
fi

# Extract project directory
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

# Check if this is a TypeScript project
if [ -f "tsconfig.json" ]; then
  # Run TypeScript compiler in check mode (no emit)
  if command -v tsc &> /dev/null; then
    echo "🔍 TypeScript check for ${file_path##*/}..."
    npx tsc --noEmit --skipLibCheck 2>&1 | head -20 || true
  fi
fi

# Format with prettier if available
if [ -f ".prettierrc" ] || [ -f ".prettierrc.json" ] || [ -f "prettier.config.js" ]; then
  if command -v prettier &> /dev/null || [ -f "node_modules/.bin/prettier" ]; then
    echo "✨ Formatting ${file_path##*/}..."
    npx prettier --write "$file_path" 2>/dev/null || true
  fi
fi

# Run ESLint if available
if [ -f ".eslintrc.json" ] || [ -f ".eslintrc.js" ] || [ -f "eslint.config.js" ]; then
  if command -v eslint &> /dev/null || [ -f "node_modules/.bin/eslint" ]; then
    echo "🔧 Linting ${file_path##*/}..."
    npx eslint --fix "$file_path" 2>&1 | head -10 || true
  fi
fi

# Auto-run tests if this is a test file modification
if [[ "$file_path" == *".test."* ]] || [[ "$file_path" == *".spec."* ]]; then
  if [ -f "package.json" ] && grep -q '"test"' package.json; then
    echo "🧪 Running tests for ${file_path##*/}..."
    npm test -- "$file_path" 2>&1 | head -30 || true
  fi
fi

exit 0