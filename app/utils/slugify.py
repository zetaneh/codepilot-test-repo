import re

def slugify(text: str) -> str:
    """
    Converts a given string into a URL-friendly slug.

    - Converts to lowercase.
    - Replaces spaces and non-alphanumeric characters (except hyphens) with hyphens.
    - Removes leading/trailing hyphens.
    - Collapses multiple hyphens into a single hyphen.
    """
    if not text:
        return ""
    text = text.lower()
    # Replace non-alphanumeric characters with hyphens
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    # Replace spaces with hyphens
    text = re.sub(r'\s+', '-', text)
    # Remove leading/trailing hyphens
    text = text.strip('-')
    # Collapse multiple hyphens
    text = re.sub(r'-+', '-', text)
    return text
