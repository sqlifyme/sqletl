from sqletl.datatable import DataTable, DictDataTable


def test_datatable():
    dt = DataTable(["a", "b"], [[0, 1], [2, 3]])
    assert dt.cols == [(None, "a"), (None, "b")]
    assert dt.colnames == ["a", "b"]
    assert dt.prefixed_cols == ["a", "b"]
    assert dt.idx_by_sources == {None: {"a": 0, "b": 1}}
    assert dt.idx_by_unique_names == {"a": 0, "b": 1}

    first = dt.peek()
    assert first == [0, 1]
    assert not dt.is_empty()
    assert not dt.started
    assert not dt.stopped
    assert dt.count == 0
    assert list(dt) == [[0, 1], [2, 3]]
    assert dt.started
    assert dt.stopped
    assert dt.count == 2
    assert not dt.is_empty()
    assert dt.get(first, "a") == 0
    assert dt.get(first, "b") == 1


def test_as_dict():
    dt = DataTable(["a", "b"], [[0, 1], [2, 3]])
    assert dt.to_dict() == [{"a": 0, "b": 1}, {"a": 2, "b": 3}]


def test_rename_source():
    dt = DataTable(["a", "b"], [[0, 1], [2, 3]])
    dt.rename_source(None, "src")
    assert dt.cols == [("src", "a"), ("src", "b")]
    assert dt.colnames == ["a", "b"]
    assert dt.prefixed_cols == ["src__a", "src__b"]
    assert dt.idx_by_sources == {"src": {"a": 0, "b": 1}}
    assert dt.idx_by_unique_names == {"a": 0, "b": 1}


def test_multi_source():
    dt = DataTable(["a", "b", ("src", "c"), ("src", "d")], [[0, 1, 3, 4], [5, 6, 7, 8]])

    assert dt.cols == [(None, "a"), (None, "b"), ("src", "c"), ("src", "d")]
    assert dt.colnames == ["a", "b", "c", "d"]
    assert dt.prefixed_cols == ["a", "b", "src__c", "src__d"]
    assert dt.idx_by_sources == {
        None: {"a": 0, "b": 1},
        "src": {"c": 2, "d": 3},
    }
    assert dt.idx_by_unique_names == {"a": 0, "b": 1, "c": 2, "d": 3}

    first = dt.peek()
    assert list(dt) == [[0, 1, 3, 4], [5, 6, 7, 8]]
    assert dt.get(first, "a") == 0
    assert dt.get(first, "b") == 1
    assert dt.get(first, "c") == 3
    assert dt.get(first, "c", "src") == 3
    assert dt.get(first, "d", "src") == 4


def test_multi_source_as_dict():
    dt = DataTable(["a", "b"], [[0, 1, 3, 4], [5, 6, 7, 8]])
    dt.add_columns(["c", "d"], "src")
    assert dt.to_dict() == [{"a": 0, "b": 1, "c": 3, "d": 4}, {"a": 5, "b": 6, "c": 7, "d": 8}]


def test_dict_datatable():
    dt = DictDataTable([{"a": 0, "b": 1}, {"a": 2, "b": 3}])
    assert dt.cols == [(None, "a"), (None, "b")]
    assert list(dt) == [(0, 1), (2, 3)]