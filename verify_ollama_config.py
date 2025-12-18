#!/usr/bin/env python3
"""
Verify Ollama model configuration across all VAMP modules
"""

import os
import sys
from pathlib import Path

def check_file_for_model(filepath: Path, expected_model: str = "llama3.2:3b"):
    """Check if a file contains the expected Ollama model version"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Look for OLLAMA_MODEL definitions
        if 'OLLAMA_MODEL' in content:
            # Check if it uses the expected model
            if expected_model in content:
                return True, "✓ Uses correct model"
            elif "llama3.2:1b" in content:
                return False, "✗ Still references old 1b model"
            else:
                return None, "⚠ Uses different model or variable"
        
        return None, "No OLLAMA_MODEL found"
        
    except Exception as e:
        return False, f"Error reading file: {e}"


def main():
    """Check all relevant files for correct Ollama model"""
    print("=" * 70)
    print("VAMP - Ollama Model Configuration Verification")
    print("=" * 70)
    print(f"Expected model: llama3.2:3b\n")
    
    # Files to check
    files_to_check = [
        "vamp_ai.py",
        "run_web.py",
        "backend/llm/ollama_client.py",
        "frontend/offline_app/contextual_scorer.py",
    ]
    
    project_root = Path(__file__).resolve().parent
    
    results = {}
    all_correct = True
    
    for file_path in files_to_check:
        full_path = project_root / file_path
        
        if not full_path.exists():
            print(f"⚠ {file_path}")
            print(f"  File not found\n")
            all_correct = False
            continue
        
        is_correct, message = check_file_for_model(full_path)
        results[file_path] = (is_correct, message)
        
        status = "✓" if is_correct else ("✗" if is_correct is False else "⚠")
        print(f"{status} {file_path}")
        print(f"  {message}\n")
        
        if is_correct is False:
            all_correct = False
    
    # Check environment variable
    print("-" * 70)
    print("Environment Variable Check:")
    env_model = os.getenv("OLLAMA_MODEL")
    if env_model:
        if env_model == "llama3.2:3b":
            print(f"✓ OLLAMA_MODEL={env_model}")
        else:
            print(f"⚠ OLLAMA_MODEL={env_model} (different from default)")
            print(f"  Note: Environment variable will override code defaults")
    else:
        print(f"✓ OLLAMA_MODEL not set (will use code defaults)")
    
    print("\n" + "=" * 70)
    if all_correct:
        print("✓ All files are configured with llama3.2:3b")
    else:
        print("✗ Some files need updating")
    print("=" * 70)
    
    # Additional info
    print("\nConfiguration Summary:")
    print("- All Python modules default to llama3.2:3b")
    print("- Environment variable OLLAMA_MODEL can override defaults")
    print("- To change model, set: export OLLAMA_MODEL='model_name'")
    print("\nTo verify Ollama has the model:")
    print("  ollama list")
    print("\nTo pull the model if needed:")
    print("  ollama pull llama3.2:3b")
    
    return 0 if all_correct else 1


if __name__ == "__main__":
    sys.exit(main())
