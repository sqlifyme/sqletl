from sqletl.protocols import expand_params
import json


def test_expand_params():
    # Test case 1: Simple key-value pair
    params = [("key", "value")]
    expected = {"key": "value"}
    assert expand_params(params) == expected

    # Test case 2: Nested key-value pair
    params = [("key.subkey", "value")]
    expected = {"key": {"subkey": "value"}}
    assert expand_params(params) == expected

    # Test case 3: JSON value
    params = [("key", json.dumps({"subkey": "value"}))]
    expected = {"key": {"subkey": "value"}}
    assert expand_params(params) == expected

    # Test case 4: Array notation
    params = [("key[]", "value1"), ("key[]", "value2")]
    expected = {"key": ["value1", "value2"]}
    assert expand_params(params) == expected

    # Test case 5: Nested array notation
    params = [("key.subkey[]", "value1"), ("key.subkey[]", "value2")]
    expected = {"key": {"subkey": ["value1", "value2"]}}
    assert expand_params(params) == expected

    # Test case 6: Complex nested structure
    params = [
        ("key1.subkey1", "value1"),
        ("key1.subkey2[]", "value2"),
        ("key1.subkey2[]", "value3"),
        ("key2", json.dumps({"subkey3": "value4"}))
    ]
    expected = {
        "key1": {
            "subkey1": "value1",
            "subkey2": ["value2", "value3"]
        },
        "key2": {
            "subkey3": "value4"
        }
    }
    assert expand_params(params) == expected
