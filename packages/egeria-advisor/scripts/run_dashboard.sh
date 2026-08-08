#!/bin/bash
# Launch monitoring dashboard (terminal or Streamlit)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}Egeria Advisor Monitoring Dashboard${NC}"
echo ""

# Check if dashboard dependencies are installed
check_streamlit() {
    python -c "import streamlit" 2>/dev/null
    return $?
}

# Show menu
echo "Select dashboard type:"
echo "  1) Terminal Dashboard (text-based, lightweight)"
echo "  2) Streamlit Dashboard (web-based, interactive)"
echo ""
read -p "Enter choice [1-2]: " choice

case $choice in
    1)
        echo -e "${GREEN}Launching Terminal Dashboard...${NC}"
        echo "Press Ctrl+C to exit"
        echo ""
        python advisor/dashboard/terminal_dashboard.py
        ;;
    2)
        if ! check_streamlit; then
            echo -e "${YELLOW}Streamlit not installed. Installing dashboard dependencies...${NC}"
            pip install -e ".[dashboard]"
        fi
        
        echo -e "${GREEN}Launching Streamlit Dashboard...${NC}"
        echo "Dashboard will open in your browser at http://localhost:8501"
        echo "Press Ctrl+C to stop the server"
        echo ""
        streamlit run advisor/dashboard/streamlit_dashboard.py
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac