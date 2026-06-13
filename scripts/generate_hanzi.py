import sys
from pathlib import Path

# Define the Unicode ranges (inclusive start, inclusive end)
# We merged contiguous and adjacent blocks from your list to optimize and simplify iteration.
HANZI_RANGES = [
    # 3.0, 13.0
    (0x3400, 0x4DBF),       # CJK Unified Ideographs Extension A (U+3400..U+4DB5) + U+4DB6..U+4DBF
    # 1.1, 4.1, 5.1, 5.2, 6.1, 8.0, 10.0, 11.0, 13.0, 14.0
    (0x4E00, 0x9FFF),       # CJK Unified Ideographs (U+4E00..U+9FA5) + all extensions up to U+9FFF
    # CJK Compatibility Ideographs
    (0xF900, 0xFA6D),       # U+F900..U+FA2D + U+FA2E..U+FA2F + U+FA30..U+FA6A + U+FA6B..U+FA6D
    (0xFA70, 0xFAD9),       # U+FA70..U+FAD9
    # Plane 2 (Supplementary Ideographic Plane)
    (0x20000, 0x2A6DF),     # CJK Unified Ideographs Extension B (U+20000..U+2A6D6) + Extensions up to U+2A6DF
    (0x2A700, 0x2B81D),     # CJK Unified Ideographs Extension C (U+2A700..U+2B73F) + Extension D (U+2B740..U+2B81D)
    (0x2B820, 0x2CEAD),     # CJK Unified Ideographs Extension E (U+2B820..U+2CEA1) + Extension E Additions
    (0x2CEB0, 0x2EBE0),     # CJK Unified Ideographs Extension F
    (0x2EBF0, 0x2EE5D),     # CJK Unified Ideographs Extension I
    (0x2F800, 0x2FA1D),     # CJK Compatibility Ideographs Supplement
    # Plane 3 (Tertiary Ideographic Plane)
    (0x30000, 0x3134A),     # CJK Unified Ideographs Extension G
    (0x31350, 0x323AF),     # CJK Unified Ideographs Extension H
    (0x323B0, 0x33479),     # CJK Unified Ideographs Extension J
]

def generate_hanzi(output_path=None):
    count = 0
    # Use utf-8 encoding to support full range of Unicode characters, especially Plane 2 and Plane 3
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # We can write them all in one line, or separated by newlines, or as comma-separated
        # Writing one character per line is most robust for list processing
        with open(path, "w", encoding="utf-8") as f:
            for start, end in HANZI_RANGES:
                for cp in range(start, end + 1):
                    f.write(chr(cp) + "\n")
                    count += 1
        print(f"Successfully generated and wrote {count} characters to {output_path}")
    else:
        # Just return as list or generator
        characters = []
        for start, end in HANZI_RANGES:
            for cp in range(start, end + 1):
                characters.append(chr(cp))
                count += 1
        print(f"Generated {count} characters in memory.")
        return characters

    return count

if __name__ == "__main__":
    out_file = "data/processed/all_unicode_hanzi.txt"
    generate_hanzi(out_file)
