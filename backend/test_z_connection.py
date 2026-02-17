import asyncio
import os
import sys
from dotenv import load_dotenv

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ai.provider import get_provider
from models.game import GameState, StructuredDecree

async def main():
    print("Initiating live API test for Z Provider...")
    
    # Force reload env to be sure
    load_dotenv()
    
    try:
        provider = get_provider("Z")
        print(f"Provider class: {type(provider)}")
        
        # We need to access the inner provider to use the client directly for a simple test
        # or we can try to use one of the public methods if we mock enough state.
        # Direct client access is safer for a connectivity test.
        inner = provider._inner
        
        print(f"Testing connection to: {inner.client.base_url}")
        print(f"Using model: {inner.model}")
        
        response = await inner.client.chat.completions.create(
            model=inner.model,
            messages=[
                {"role": "user", "content": "Hello, say 'Connection Successful' if you can hear me."}
            ],
            max_tokens=20
        )
        
        content = response.choices[0].message.content
        print("\n--- API Response ---")
        print(content)
        print("--------------------")
        print("\nTest PASSED: Successfully received response from API.")
        
    except Exception as e:
        with open("test_result.txt", "w", encoding="utf-8") as f:
            f.write(f"Test FAILED: {e}\n")
        print(f"\nTest FAILED: {e}")
        import traceback
        traceback.print_exc()
    else:
        with open("test_result.txt", "w", encoding="utf-8") as f:
            f.write("Test PASSED: Successfully received response from API.\n")
            f.write(content)

if __name__ == "__main__":
    asyncio.run(main())
