#!/bin/bash

# Kaizen Anime Downloader - Start Script
# Author: Trex

clear

echo "🚀 Starting Kaizen Anime Downloader..."
echo ""

# Check if Python3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python3 is not installed."
    echo "Please install Python3 and try again."
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "⚠️  Virtual environment not found."
    echo "Running installation script..."
    echo ""
    chmod +x install.sh
    ./install.sh
    
    if [ $? -ne 0 ]; then
        echo "❌ Installation failed. Please check the errors above."
        exit 1
    fi
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Run the downloader
echo "✅ Launching Kaizen..."
echo ""
python3 anime_downloader.py

# Deactivate virtual environment when done
deactivate

echo ""
echo "👋 Thanks for using Kaizen!"
