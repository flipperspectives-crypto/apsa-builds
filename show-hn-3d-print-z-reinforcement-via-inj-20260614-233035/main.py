#!/usr/bin/env python3
"""Show HN: 3D print Z reinforcement via injected loops — CLI Tool
Source: [HN] https://mgunlogson.github.io/magma/
"""

import argparse, json, os, sys
from pathlib import Path

def process(input_path: str, output_path: str, **kwargs) -> dict:
    """Core processing logic."""
    path = Path(input_path)
    if not path.exists():
        return {"error": f"File not found: {input_path}"}
    
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")
    words = content.split()
    
    result = {
        "file": str(path),
        "size_bytes": len(content.encode()),
        "lines": len(lines),
        "words": len(words),
        "chars": len(content),
        "preview": content[:500]
    }
    
    Path(output_path).write_text(json.dumps(result, indent=2))
    return result

def main():
    parser = argparse.ArgumentParser(description="Show HN: 3D print Z reinforcement via injected loops")
    parser.add_argument("input", help="Input file or text")
    parser.add_argument("-o", "--output", default="output.json", help="Output file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    print(f"⚙️  Processing {args.input}...")
    result = process(args.input, args.output)
    
    if "error" in result:
        print(f"❌ {result['error']}")
        sys.exit(1)
    
    print(f"✅ {result['lines']} lines, {result['words']} words, {result['size_bytes']} bytes")
    print(f"   Saved: {args.output}")
    
    if args.verbose:
        print(f"\n{result['preview'][:300]}")

if __name__ == "__main__":
    main()
