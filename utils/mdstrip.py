
import re

def strip_markdown(text: str) -> str:
    """
    Removes all markdown formatting from a given string.

    Args:
        text: The input string with markdown.

    Returns:
        The string with all markdown formatting removed.
    """
    # Remove code blocks (e.g., ```python\ncode\n```) - Do this first to avoid issues with other patterns inside code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

    # Remove inline code (e.g., `code`)
    text = re.sub(r'`(.*?)`', r'\1', text)

    # Remove images (e.g., ![alt text](url)) - Keep alt text
    text = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', text)

    # Remove links (e.g., [text](url)) - Keep link text
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)

    # Remove bold and italic (e.g., **bold**, *italic*, __bold__, _italic_)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)

    # Remove headers (e.g., # Header, ## Subheader) - Keep header text
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)

    # Remove blockquotes (e.g., > Quote) - Keep quote text
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)

    # Remove list markers (e.g., - item, * item, 1. item) - Keep list item text
    text = re.sub(r'^[*-]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s*', '', text, flags=re.MULTILINE)

    # Replace multiple newlines with a single newline and strip leading/trailing whitespace
    text = re.sub(r'\n\s*\n', '\n', text)
    text = text.strip()

    return text

if __name__ == "__main__":
    markdown_text = """
# This is a Header

## This is a Subheader

This is some **bold text** and *italic text*.
Also, some __underline bold__ and _underline italic_.

Here is a [link to Google](https://www.google.com).
And an image: ![Alt text for image](https://example.com/image.jpg)

Inline code: `print("Hello, World!")`

```python
def greet(name):
    return f"Hello, {name}!"
```

> This is a blockquote.
> It can span multiple lines.

- List item 1
* List item 2
1. Ordered list item 1
2. Ordered list item 2

Another paragraph.
"""

    stripped_text = strip_markdown(markdown_text)
    print("Original Markdown:")
    print(markdown_text)
    print("\n" + "="*30 + "\n")
    print("Stripped Text:")
    print(stripped_text)
