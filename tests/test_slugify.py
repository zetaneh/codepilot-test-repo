import pytest
from app.utils.slugify import slugify

@pytest.mark.parametrize(
    "input_string, expected_slug",
    [
        ("Hello World", "hello-world"),
        ("Another Test String", "another-test-string"),
        ("  leading and trailing spaces  ", "leading-and-trailing-spaces"),
        ("Multiple   Spaces Here", "multiple-spaces-here"),
        ("Special!@#$%^&*()Characters", "specialcharacters"),
        ("Text with-hyphens", "text-with-hyphens"),
        ("Already-a-slug", "already-a-slug"),
        ("", ""),
        ("   ", ""),
        ("UPPERCASE TEXT", "uppercase-text"),
        ("123 Numbers 456", "123-numbers-456"),
        ("  -leading-hyphen", "leading-hyphen"),
        ("trailing-hyphen-  ", "trailing-hyphen"),
        ("Mixed Case String With Numbers 123!@#", "mixed-case-string-with-numbers-123"),
        ("A string with a very long title that should be slugified correctly and handle all edge cases",
         "a-string-with-a-very-long-title-that-should-be-slugified-correctly-and-handle-all-edge-cases"),
        ("  !@#$ special chars only #$!@  ", ""),
        ("  -!@#$ special chars and hyphens #$!@-", "special-chars-and-hyphens"),
    ],
)
def test_slugify(input_string, expected_slug):
    assert slugify(input_string) == expected_slug
