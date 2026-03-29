import pytest
import subprocess
import json
from utils.csvparser import parse_csv

# Unit Tests for parse_csv function

def test_parse_csv_basic():
    csv_input = "header1,header2\nvalue1,value2"
    expected_output = [{'header1': 'value1', 'header2': 'value2'}]
    assert parse_csv(csv_input) == expected_output

def test_parse_csv_multiple_rows():
    csv_input = "name,age\nAlice,30\nBob,24"
    expected_output = [
        {'name': 'Alice', 'age': '30'},
        {'name': 'Bob', 'age': '24'}
    ]
    assert parse_csv(csv_input) == expected_output

def test_parse_csv_empty_input():
    csv_input = ""
    expected_output = []
    assert parse_csv(csv_input) == expected_output

def test_parse_csv_only_headers():
    csv_input = "col1,col2,col3"
    expected_output = []
    assert parse_csv(csv_input) == expected_output

def test_parse_csv_with_commas_in_fields():
    csv_input = 'name,description\n"Alice","A person, with a comma"'
    expected_output = [{'name': 'Alice', 'description': 'A person, with a comma'}]
    assert parse_csv(csv_input) == expected_output

def test_parse_csv_with_missing_values():
    csv_input = "col1,col2\nval1,\n,val4"
    expected_output = [
        {'col1': 'val1', 'col2': ''},
        {'col1': '', 'col2': 'val4'}
    ]
    assert parse_csv(csv_input) == expected_output

def test_parse_csv_different_delimiter():
    # The default csv.DictReader uses comma, so this test will fail if not handled.
    # For this subtask, we assume comma is the delimiter.
    csv_input = "col1;col2\nval1;val2"
    expected_output = [{'col1;col2': 'val1;val2'}]
    assert parse_csv(csv_input) == expected_output

# Integration Tests for CLI

def run_csvparser_cli(csv_input: str) -> dict:
    process = subprocess.run(
        ["python3", "utils/csvparser.py"],
        input=csv_input.encode('utf-8'),
        capture_output=True,
        check=True
    )
    return json.loads(process.stdout.decode('utf-8'))

def test_cli_basic():
    csv_input = "header1,header2\nvalue1,value2"
    expected_output = [{'header1': 'value1', 'header2': 'value2'}]
    assert run_csvparser_cli(csv_input) == expected_output

def test_cli_multiple_rows():
    csv_input = "name,age\nAlice,30\nBob,24"
    expected_output = [
        {'name': 'Alice', 'age': '30'},
        {'name': 'Bob', 'age': '24'}
    ]
    assert run_csvparser_cli(csv_input) == expected_output

def test_cli_empty_input():
    csv_input = ""
    expected_output = []
    assert run_csvparser_cli(csv_input) == expected_output

def test_cli_only_headers():
    csv_input = "col1,col2,col3"
    expected_output = []
    assert run_csvparser_cli(csv_input) == expected_output

def test_cli_with_commas_in_fields():
    csv_input = 'name,description\n"Alice","A person, with a comma"'
    expected_output = [{'name': 'Alice', 'description': 'A person, with a comma'}]
    assert run_csvparser_cli(csv_input) == expected_output

def test_cli_with_missing_values():
    csv_input = "col1,col2\nval1,\n,val4"
    expected_output = [
        {'col1': 'val1', 'col2': ''},
        {'col1': '', 'col2': 'val4'}
    ]
    assert run_csvparser_cli(csv_input) == expected_output
