import csv
import io
import json
import sys

def parse_csv(csv_data: str) -> list[dict]:
    """
    Parses a CSV string into a list of dictionaries.

    Args:
        csv_data: A string containing CSV data.

    Returns:
        A list of dictionaries, where each dictionary represents a row
        and keys are the column headers.
    """
    f = io.StringIO(csv_data)
    reader = csv.DictReader(f)
    return list(reader)

if __name__ == "__main__":
    csv_input = sys.stdin.read()
    parsed_data = parse_csv(csv_input)
    json.dump(parsed_data, sys.stdout, indent=2)
    sys.stdout.write("\n")
