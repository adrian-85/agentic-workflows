#!/bin/bash
# approval-gate.sh - Handle approval prompts with user input
#
# Usage: approval-gate.sh <gate-name> <proposal-file>
#
# Input:
#   $1: Gate name (e.g., "analysis", "quality-review", "final")
#   $2: Path to proposal file (markdown or JSON)
#
# Output: Exit code
#   0: Approved
#   1: Declined
#   2: Modifications requested
#
# For modifications, writes user feedback to <proposal-file>.feedback

set -euo pipefail

# Check arguments
if [ $# -lt 2 ]; then
    echo "Usage: approval-gate.sh <gate-name> <proposal-file>" >&2
    exit 1
fi

GATE_NAME="$1"
PROPOSAL_FILE="$2"

# Check if proposal file exists
if [ ! -f "$PROPOSAL_FILE" ]; then
    echo "Error: Proposal file not found: $PROPOSAL_FILE" >&2
    exit 1
fi

# Display gate header
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  APPROVAL GATE: $GATE_NAME"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Display proposal content
cat "$PROPOSAL_FILE"
echo ""

# Display options
echo "────────────────────────────────────────────────────────────────"
echo "  Options:"
echo "    [a] Approve - Proceed with implementation"
echo "    [d] Decline - Stop workflow"
echo "    [m] Modify  - Request changes"
echo "────────────────────────────────────────────────────────────────"
echo ""

# Get user input
while true; do
    read -p "  Your choice (a/d/m): " choice
    case "${choice,,}" in
        a|approve)
            echo ""
            echo "  ✓ Approved"
            echo ""
            exit 0
            ;;
        d|decline)
            echo ""
            echo "  ✗ Declined - Workflow stopped"
            echo ""
            exit 1
            ;;
        m|modify)
            echo ""
            echo "  Enter your modification requests (end with empty line):"
            echo "  ────────────────────────────────────────────────────────"
            
            # Collect multi-line input
            feedback=""
            while IFS= read -r line; do
                if [ -z "$line" ]; then
                    break
                fi
                feedback="${feedback}${line}"$'\n'
            done
            
            # Write feedback to file
            feedback_file="${PROPOSAL_FILE}.feedback"
            echo "$feedback" > "$feedback_file"
            
            echo "  ────────────────────────────────────────────────────────"
            echo "  ✓ Feedback saved to: $feedback_file"
            echo "  ✓ Please review and resubmit after modifications"
            echo ""
            exit 2
            ;;
        *)
            echo "  Invalid choice. Please enter a, d, or m"
            ;;
    esac
done
