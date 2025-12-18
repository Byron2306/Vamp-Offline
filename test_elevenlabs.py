#!/usr/bin/env python3
"""
Test script for ElevenLabs TTS integration
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

def test_elevenlabs_import():
    """Test that ElevenLabs module can be imported"""
    print("=" * 60)
    print("Testing ElevenLabs TTS Module Import")
    print("=" * 60)
    
    try:
        from backend.llm.elevenlabs_tts import ElevenLabsTTS, text_to_speech, sanitize_for_speech
        print("✓ Successfully imported ElevenLabs TTS module")
        return True
    except ImportError as e:
        print(f"✗ Failed to import ElevenLabs TTS: {e}")
        return False


def test_text_sanitization():
    """Test text sanitization function"""
    print("\n" + "=" * 60)
    print("Testing Text Sanitization")
    print("=" * 60)
    
    from backend.llm.elevenlabs_tts import sanitize_for_speech
    
    test_cases = [
        ("Hello **world**", "Hello world"),
        ("This has *asterisks*", "This has asterisks"),
        ("Multiple ***asterisks***", "Multiple asterisks"),
        ("With `code` blocks", "With code blocks"),
        ("Bullet points:\n- Item 1\n- Item 2", "Bullet points:\nItem 1\nItem 2"),
        ("Check [this link](http://example.com)", "Check this link"),
    ]
    
    all_passed = True
    for input_text, expected in test_cases:
        result = sanitize_for_speech(input_text)
        if result.strip() == expected.strip():
            print(f"✓ '{input_text[:30]}...' → '{result[:30]}...'")
        else:
            print(f"✗ '{input_text[:30]}...'")
            print(f"  Expected: '{expected}'")
            print(f"  Got: '{result}'")
            all_passed = False
    
    return all_passed


def test_elevenlabs_connection():
    """Test connection to ElevenLabs API"""
    print("\n" + "=" * 60)
    print("Testing ElevenLabs API Connection")
    print("=" * 60)
    
    from backend.llm.elevenlabs_tts import get_tts_client
    
    try:
        client = get_tts_client()
        print(f"✓ TTS client initialized")
        print(f"  - Cache directory: {client.cache_dir}")
        print(f"  - Voice ID: {client.VOICE_ID}")
        
        # Check quota
        print("\nChecking API quota...")
        quota = client.check_quota()
        if quota:
            print(f"✓ API connection successful")
            print(f"  - Character count: {quota.get('character_count', 0)}")
            print(f"  - Character limit: {quota.get('character_limit', 0)}")
            remaining = quota.get('character_limit', 0) - quota.get('character_count', 0)
            print(f"  - Characters remaining: {remaining}")
        else:
            print("⚠ Could not fetch quota (may indicate API issue)")
        
        # Get voice info
        print("\nFetching voice information...")
        voice_info = client.get_voice_info()
        if voice_info:
            print(f"✓ Voice information retrieved")
            print(f"  - Voice name: {voice_info.get('name', 'Unknown')}")
            print(f"  - Labels: {voice_info.get('labels', {})}")
        else:
            print("⚠ Could not fetch voice info")
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_speech_generation():
    """Test generating a short speech sample"""
    print("\n" + "=" * 60)
    print("Testing Speech Generation")
    print("=" * 60)
    
    from backend.llm.elevenlabs_tts import text_to_speech
    
    test_text = "Hello, I am VAMP, your Virtual Academic Management Partner."
    
    print(f"Generating speech for: '{test_text}'")
    
    try:
        audio_path = text_to_speech(test_text)
        
        if audio_path and audio_path.exists():
            print(f"✓ Speech generated successfully!")
            print(f"  - Audio file: {audio_path}")
            print(f"  - File size: {audio_path.stat().st_size} bytes")
            return True
        else:
            print("✗ Speech generation returned None or file not found")
            return False
            
    except Exception as e:
        print(f"✗ Error generating speech: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_vamp_ai_integration():
    """Test integration with vamp_ai.py"""
    print("\n" + "=" * 60)
    print("Testing VAMP AI Integration")
    print("=" * 60)
    
    try:
        from vamp_ai import ask_vamp
        
        print("Testing ask_vamp with voice generation...")
        
        context = {
            "staff_id": "TEST001",
            "cycle_year": 2025,
            "stage": "testing"
        }
        
        # Test without voice
        print("\n1. Testing text-only response...")
        result = ask_vamp("What is VAMP?", context, with_voice=False)
        if result.get('answer'):
            print(f"✓ Text response received")
            print(f"  Answer: {result['answer'][:100]}...")
        else:
            print(f"✗ No answer in response")
            return False
        
        # Test with voice
        print("\n2. Testing response with voice...")
        result = ask_vamp("Hello VAMP, how are you?", context, with_voice=True)
        if result.get('answer'):
            print(f"✓ Text response received")
            print(f"  Answer: {result['answer'][:100]}...")
            
            if result.get('has_voice'):
                print(f"✓ Voice generated")
                print(f"  Audio path: {result.get('audio_path')}")
            else:
                print(f"⚠ Voice not generated (may be expected if Ollama not running)")
        else:
            print(f"✗ No answer in response")
            return False
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("VAMP - ElevenLabs TTS Integration Test Suite")
    print("=" * 60)
    
    results = {}
    
    # Run tests
    results['import'] = test_elevenlabs_import()
    
    if results['import']:
        results['sanitization'] = test_text_sanitization()
        results['connection'] = test_elevenlabs_connection()
        results['generation'] = test_speech_generation()
        results['vamp_integration'] = test_vamp_ai_integration()
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed. Check output above for details.")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
