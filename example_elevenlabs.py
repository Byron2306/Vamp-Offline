#!/usr/bin/env python3
"""
Simple example demonstrating ElevenLabs TTS with VAMP
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

def example_basic_tts():
    """Basic text-to-speech example"""
    print("=" * 60)
    print("Example 1: Basic Text-to-Speech")
    print("=" * 60)
    
    from backend.llm.elevenlabs_tts import text_to_speech
    
    # Simple text
    text = "Hello! I am VAMP, your Virtual Academic Management Partner at North-West University."
    
    print(f"Converting to speech: '{text}'")
    
    audio_path = text_to_speech(text)
    
    if audio_path:
        print(f"✓ Audio generated: {audio_path}")
        print(f"  File size: {audio_path.stat().st_size / 1024:.1f} KB")
        print(f"\nYou can play it with:")
        print(f"  play {audio_path}")
        print(f"  or")
        print(f"  ffplay {audio_path}")
    else:
        print("✗ Failed to generate audio")


def example_sanitized_text():
    """Example with text that needs sanitization"""
    print("\n" + "=" * 60)
    print("Example 2: Sanitized Text (removing markdown)")
    print("=" * 60)
    
    from backend.llm.elevenlabs_tts import text_to_speech, sanitize_for_speech
    
    # Text with markdown and symbols
    messy_text = """
    **Welcome to VAMP!**
    
    Here are your *key tasks*:
    - Complete assessment rubrics
    - Upload evidence documents
    - Review your KPAs
    
    For more info, check [this link](http://example.com).
    """
    
    print("Original text (with markdown):")
    print(messy_text)
    
    clean_text = sanitize_for_speech(messy_text)
    print("\nCleaned text (for speech):")
    print(clean_text)
    
    print("\nGenerating speech from cleaned text...")
    audio_path = text_to_speech(messy_text)  # text_to_speech calls sanitize automatically
    
    if audio_path:
        print(f"✓ Audio generated: {audio_path}")
    else:
        print("✗ Failed to generate audio")


def example_vamp_ai_with_voice():
    """Example using VAMP AI with voice response"""
    print("\n" + "=" * 60)
    print("Example 3: VAMP AI with Voice")
    print("=" * 60)
    
    from vamp_ai import ask_vamp
    
    # Context about the staff member
    context = {
        "staff_id": "20172672",
        "cycle_year": 2025,
        "stage": "planning",
        "tasks": "Research, Teaching, Service"
    }
    
    question = "What are the main areas I need to focus on for my performance agreement?"
    
    print(f"Question: {question}")
    print("\nAsking VAMP AI (with voice)...\n")
    
    # Ask VAMP with voice generation
    result = ask_vamp(question, context, with_voice=True)
    
    print("Response:")
    print("-" * 60)
    print(result['answer'])
    print("-" * 60)
    
    if result.get('has_voice'):
        print(f"\n✓ Voice response generated: {result.get('audio_path')}")
    else:
        print("\n⚠ Voice not generated (Ollama may not be running)")


def example_check_quota():
    """Check remaining ElevenLabs quota"""
    print("\n" + "=" * 60)
    print("Example 4: Check API Quota")
    print("=" * 60)
    
    from backend.llm.elevenlabs_tts import get_tts_client
    
    client = get_tts_client()
    
    print("Checking ElevenLabs API quota...")
    
    quota = client.check_quota()
    
    if quota:
        used = quota['character_count']
        limit = quota['character_limit']
        remaining = limit - used
        percentage = (remaining / limit) * 100
        
        print(f"\n✓ Quota Status:")
        print(f"  Characters used: {used:,}")
        print(f"  Characters limit: {limit:,}")
        print(f"  Characters remaining: {remaining:,}")
        print(f"  Percentage remaining: {percentage:.1f}%")
        
        # Estimate remaining responses
        avg_response_length = 200  # characters
        estimated_responses = remaining // avg_response_length
        print(f"\n  Estimated remaining responses: ~{estimated_responses}")
    else:
        print("✗ Could not fetch quota")
    
    # Get voice info
    print("\nVoice Information:")
    voice_info = client.get_voice_info()
    
    if voice_info:
        print(f"  Name: {voice_info.get('name')}")
        labels = voice_info.get('labels', {})
        print(f"  Accent: {labels.get('accent')}")
        print(f"  Gender: {labels.get('gender')}")
        print(f"  Age: {labels.get('age')}")
        print(f"  Language: {labels.get('language')}")
    else:
        print("  Could not fetch voice info")


def main():
    """Run all examples"""
    print("\n" + "=" * 60)
    print("VAMP - ElevenLabs TTS Examples")
    print("=" * 60)
    
    try:
        # Run examples
        example_basic_tts()
        example_sanitized_text()
        example_vamp_ai_with_voice()
        example_check_quota()
        
        print("\n" + "=" * 60)
        print("✓ All examples completed!")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Start the web server: python run_web.py")
        print("  2. Open browser: http://localhost:5000")
        print("  3. Try asking VAMP questions with voice responses")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
