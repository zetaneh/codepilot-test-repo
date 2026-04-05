import re
import sys

def slugify(text: str) -> str:
    """
    Converts text into a URL-friendly slug.

    The function converts text to lowercase, replaces spaces with hyphens,
    removes non-alphanumeric characters (except hyphens), collapses multiple
    hyphens, and strips leading/trailing hyphens.
    """
    text = text.lower()
    text = re.sub(r'\s+', '-', text)  # Replace spaces with hyphens
    text = re.sub(r'[^a-z0-9-]', '', text)  # Remove non-alphanumeric (except hyphens)
    text = re.sub(r'-+', '-', text)  # Collapse multiple hyphens
    text = text.strip('-')  # Strip leading/trailing hyphens
    return text

if __name__ == '__main__':
    if len(sys.argv) > 1:
        input_text = sys.argv[1]
        slug = slugify(input_text)
        print(slug)
    else:
        print("Usage: python utils/slugify.py 'Your Text Here'")
