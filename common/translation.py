"""Translation utilities for Japanese product names."""
import re
from typing import Optional


def translate_japanese_to_english(text: str) -> str:
    """
    Translate Japanese text to English.
    Uses hybrid approach: pattern matching for brand names, Google Translate for the rest.
    """
    if not text:
        return text
    
    # If text is already mostly English, return as-is
    if is_mostly_english(text):
        return text
    
    # First, apply brand name patterns (more accurate than Google Translate for brand names)
    brand_patterns = {
        r'ジェルミーペタリー': 'Gel Me Petaly',
        r'ジェルミー': 'Gel Me',
    }
    
    preprocessed = text
    for jp_pattern, en_replacement in brand_patterns.items():
        preprocessed = re.sub(jp_pattern, en_replacement, preprocessed)
    
    # Try to use Google Translate for the rest
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='ja', target='en')
        translated = translator.translate(preprocessed)
        
        # Clean up common translation issues
        translated = translated.replace('Germy', 'Gel Me')
        translated = translated.replace('Jelmy', 'Gel Me')
        translated = translated.replace('Petary', 'Petaly')
        translated = translated.replace('Petalie', 'Petaly')
        
        print(f"[Translation] '{text}' -> '{translated}'")
        return translated
    except ImportError:
        print("[Translation] deep-translator not installed, using fallback translation")
        return fallback_translate(text)
    except Exception as e:
        print(f"[Translation] Error translating '{text}': {e}")
        return fallback_translate(text)


def is_mostly_english(text: str) -> bool:
    """Check if text is mostly English characters."""
    if not text:
        return True
    
    # Count English/ASCII characters vs total
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    total_chars = len(text)
    
    # If more than 70% is ASCII, consider it English
    return (ascii_chars / total_chars) > 0.7


def fallback_translate(text: str) -> str:
    """
    Fallback translation using pattern matching.
    This is a simple approach for common Japanese product name patterns.
    """
    # Common Japanese product name patterns
    patterns = {
        r'【(\d+)％OFF】': r'[\1% OFF] ',  # Discount tags
        r'ジェルミーペタリー': 'Gel Me Petaly',
        r'オーロラフレンチ': 'Aurora French',
        r'ココマンゴー': 'Coco Mango',
        r'アンバーフィグ': 'Amber Fig',
        r'ハニーディライト': 'Honey Delight',
        r'メルティングチーク': 'Melting Cheek',
        r'サンタモニカ': 'Santa Monica',
        r'クラウドムース': 'Cloud Mousse',
        r'プルメリア': 'Plumeria',
        r'ジェムストーン': 'Gemstone',
    }
    
    translated = text
    for jp_pattern, en_replacement in patterns.items():
        translated = re.sub(jp_pattern, en_replacement, translated)
    
    # If translation didn't change much, note that it needs manual translation
    if translated == text:
        print(f"[Translation] No pattern match for: {text}")
        # Keep original but add a note
        return f"{text} (JP)"
    
    return translated.strip()


def clean_product_name(name: str) -> str:
    """
    Clean and translate product name for English-speaking users.
    """
    if not name:
        return name
    
    # Translate if contains Japanese
    if contains_japanese(name):
        name = translate_japanese_to_english(name)
    
    # Clean up extra spaces
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name


def contains_japanese(text: str) -> bool:
    """Check if text contains Japanese characters."""
    if not text:
        return False
    
    # Japanese Unicode ranges:
    # Hiragana: 3040-309F
    # Katakana: 30A0-30FF
    # Kanji: 4E00-9FFF
    japanese_pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]')
    return bool(japanese_pattern.search(text))


# For testing
if __name__ == "__main__":
    test_names = [
        "【50％OFF】ジェルミーペタリー L5 ココマンゴー",
        "【50％OFF】ジェルミーペタリー 02 オーロラフレンチ",
        "【50％OFF】ジェルミーペタリー 06 アンバーフィグ",
        "【30％OFF】ジェルミーペタリーL12 ハニーディライト",
        "【30％OFF】ジェルミーペタリーL10 メルティングチーク",
        "【30％OFF】ジェルミーペタリーL13 サンタモニカ",
        "【30％OFF】ジェルミーペタリーL11 クラウドムース",
        "【30％OFF】ジェルミーペタリーL15 プルメリア",
        "【50％OFF】ジェルミーペタリー 05 ジェムストーン",
    ]
    
    print("Testing translation:")
    print("=" * 60)
    for name in test_names:
        translated = clean_product_name(name)
        print(f"{name}")
        print(f"  -> {translated}")
        print()
